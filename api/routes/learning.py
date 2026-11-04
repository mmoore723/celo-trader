"""Grounded learning examples built from recorded strategy episodes.

This module is deliberately read-only.  It turns the same account-scoped
candidate and candle evidence used by the audit UI into lessons, but it has no
path to strategy evaluation, sizing, or order submission.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import json
import logging
import secrets
import sqlite3
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config.strategy_catalog import REVIEWED_STRATEGIES


router = APIRouter(prefix="/api/learning", tags=["learning"])
logger = logging.getLogger("celo_trader.api.learning")


@router.get('/guide')
def learning_guide(strategy_id: str, ticker: str, version: str):
    from api.routes.learning_guide import guide
    return guide(strategy_id, ticker, version)

ExampleCategory = Literal[
    "clean_win",
    "valid_loss",
    "false_breakout_or_chop",
    "rejected_missing_condition",
    "ambiguous_no_trade",
]

CATEGORY_TARGETS: dict[ExampleCategory, int] = {
    "clean_win": 15,
    "valid_loss": 10,
    "false_breakout_or_chop": 10,
    "rejected_missing_condition": 10,
    "ambiguous_no_trade": 5,
}

_EPISODE_GAP = timedelta(minutes=15)
_ET = ZoneInfo("America/New_York")


def _et_naive(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_ET).replace(tzinfo=None)
    return parsed
def _example_category(row: dict) -> ExampleCategory:
    """Classify an episode from recorded facts only; never infer a winner."""
    reason = " ".join((
        str(row.get("gate_reason") or ""),
        str(row.get("gate_detail") or ""),
    )).lower()
    outcome = str(row.get("final_outcome") or "pending").lower()
    direction_correct = row.get("direction_correct")
    measured = row.get("outcome_observed_at") is not None or direction_correct is not None

    if any(token in reason for token in ("chop", "false break", "failed break", "whipsaw")):
        return "false_breakout_or_chop"
    if outcome == "blocked" or row.get("gate_reason"):
        return "rejected_missing_condition"
    move = row.get("directional_move_pct")
    if measured and move is not None and abs(float(move)) < 0.10:
        return "false_breakout_or_chop"
    if measured and move is not None and float(move) >= 0.10:
        return "clean_win"
    if measured and move is not None and float(move) <= -0.10:
        return "valid_loss"
    return "ambiguous_no_trade"


def _coach_copy(row: dict, category: ExampleCategory) -> dict[str, str]:
    """Return auditable teaching copy without calling a generative model."""
    rule = REVIEWED_STRATEGIES[str(row["strategy_id"])]
    direction = str(row.get("direction") or "unknown").lower()
    reason = str(row.get("gate_detail") or row.get("gate_reason") or "").strip()
    move = row.get("directional_move_pct")
    measured = f" The recorded directional move was {float(move):+.2f}%." if move is not None else ""

    if category == "clean_win":
        summary = f"This recorded {direction} {rule.display_name} candidate had positive 60-minute underlying follow-through.{measured}"
        prompt = "Which completed chart facts supported the candidate before its 60-minute direction was known?"
    elif category == "valid_loss":
        summary = f"This recorded {direction} candidate had negative 60-minute underlying follow-through. This is not option P&L.{measured}"
        prompt = "Can you review the original decision without changing its rule after seeing the 60-minute direction?"
    elif category == "false_breakout_or_chop":
        summary = f"This episode was recorded as chop or a failed breakout. {reason or 'The expected structure did not hold.'}"
        prompt = "Which completed candle first showed that continuation was no longer clean?"
    elif category == "rejected_missing_condition":
        summary = f"The scanner saw a possible {rule.display_name} shape, but the recorded gate stopped it: {reason or 'a required condition was missing.'}"
        prompt = "Which required condition is absent, and why is waiting better than forcing the trade?"
    else:
        summary = "This episode is intentionally unresolved or ambiguous. The correct learning objective is to avoid inventing certainty."
        prompt = "Would you enter, wait, or reject—and which recorded fact supports that choice?"
    return {"summary": summary, "prompt": prompt}


def _account_scope() -> tuple[str, tuple[object, ...]]:
    from config import get_settings

    account_id = get_settings().get("active_broker_account_id") or None
    if account_id:
        return "broker_account_id = ?", (account_id,)
    return "(broker_account_id IS NULL OR broker_account_id = '')", ()


def _collapse_independent_episodes(rows: list[dict]) -> list[dict]:
    """Collapse repeated detections until a 15-minute quiet gap.

    Repeated one-minute checks do not become independent examples. A group is
    represented by one complete source row, however: fields are never copied
    between candidate IDs because their outcomes and charts are inseparable.
    """
    episodes: list[dict] = []
    latest_by_key: dict[tuple[str, str, str], tuple[datetime, int]] = {}
    for source in sorted(rows, key=lambda row: str(row.get("observed_at") or "")):
        row = dict(source)
        key = (
            str(row.get("strategy_id") or ""),
            str(row.get("ticker") or ""),
            str(row.get("direction") or ""),
        )
        try:
            observed = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            episodes.append(row)
            continue
        prior = latest_by_key.get(key)
        if prior and observed - prior[0] <= _EPISODE_GAP:
            target = episodes[prior[1]]
            episode_size = int(target.get("episode_size") or 1) + 1
            target_has_resolution = bool(target.get("outcome_observed_at") or target.get("resolved_at"))
            row_has_resolution = bool(row.get("outcome_observed_at") or row.get("resolved_at"))
            if row_has_resolution and not target_has_resolution:
                row["episode_size"] = episode_size
                episodes[prior[1]] = row
            else:
                target["episode_size"] = episode_size
            latest_by_key[key] = (observed, prior[1])
            continue
        row["episode_size"] = 1
        episodes.append(row)
        latest_by_key[key] = (observed, len(episodes) - 1)
    return episodes


def _candidate_rows(strategy_id: str | None = None, *, limit: int = 1000) -> list[dict]:
    from database import get_conn

    scope, params = _account_scope()
    clauses = [scope]
    values: list[object] = list(params)
    if strategy_id:
        clauses.append("strategy_id = ?")
        values.append(strategy_id)
    values.append(limit)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_candidates WHERE " + " AND ".join(clauses)
                + " ORDER BY observed_at DESC LIMIT ?",
                tuple(values),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.info("learning ledger is not initialized yet: %s", exc)
            return []
        raise
    return [dict(row) for row in rows]


def _recorded_strategy_version(row: dict) -> str | None:
    """Read the strategy version stamped when this exact candidate was made."""
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    version = metadata.get("strategy_version")
    return str(version) if version else None


def _eligible_recorded_row(row: dict) -> bool:
    strategy_id = str(row.get("strategy_id") or "")
    rule = REVIEWED_STRATEGIES.get(strategy_id)
    return bool(
        rule
        and str(row.get("ticker") or "").upper() in rule.tickers
        and _recorded_strategy_version(row) == rule.version
    )


_CHART_OBSERVABLE_GATE_TOKENS = (
    "chop", "false_break", "market_structure", "opening_range", "pullback",
    "trend", "vwap", "fvg", "relative_volume", "rvol", "candle", "breakout",
)


def _practice_eligible(row: dict, category: ExampleCategory) -> bool:
    """Exclude account/execution blocks a learner cannot infer from OHLCV."""
    if category != "rejected_missing_condition":
        return True
    evidence = f"{row.get('gate_reason') or ''} {row.get('gate_detail') or ''}".lower()
    return any(token in evidence for token in _CHART_OBSERVABLE_GATE_TOKENS)


def _bars_for_candidate(row: dict, *, before: int = 45, after: int = 45) -> list[dict]:
    from database import get_conn

    try:
        center = _et_naive(row["observed_at"])
    except (KeyError, TypeError, ValueError):
        return []
    start = (center - timedelta(minutes=before)).isoformat()
    try:
        outcome_time = _et_naive(row["outcome_observed_at"])
    except (KeyError, TypeError, ValueError):
        outcome_time = center + timedelta(minutes=after)
    end = max(center + timedelta(minutes=after), outcome_time + timedelta(minutes=1)).isoformat()
    account_id = row.get("broker_account_id") or ""
    try:
        with get_conn() as conn:
            bars = conn.execute(
                """SELECT bar_time, open, high, low, close, volume
                   FROM scanner_candle_observations
                   WHERE broker_account_id = ? AND ticker = ? AND timeframe = '1Min'
                     AND bar_time BETWEEN ? AND ?
                   ORDER BY bar_time""",
                (account_id, str(row["ticker"]), start, end),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        # Older local databases may predate scanner candle persistence.  An
        # empty result is honest; the UI reports evidence collection progress.
        if "no such table" in str(exc).lower():
            logger.info("learning candle ledger is not initialized yet: %s", exc)
            return []
        raise
    return [{
        "time": bar["bar_time"], "open": bar["open"], "high": bar["high"],
        "low": bar["low"], "close": bar["close"], "volume": bar["volume"],
    } for bar in bars]


def _decision_bar_index(bars: list[dict], decision_at: str) -> int:
    if not bars:
        return 0
    try:
        decision_time = _et_naive(decision_at)
        completed = [
            index for index, bar in enumerate(bars)
            if _et_naive(bar["time"]) <= decision_time
        ]
        return completed[-1] if completed else 0
    except (TypeError, ValueError):
        # Fail closed: an unparseable decision time must never reveal a later
        # candle. The coverage check will exclude this episode from practice.
        return 0


def _chart_evidence(row: dict) -> tuple[list[dict], int] | None:
    bars = _bars_for_candidate(row)
    if len(bars) < 10:
        return None
    decision_at = row.get("trigger_bar") or row["observed_at"]
    try:
        _et_naive(decision_at)
    except (TypeError, ValueError):
        decision_at = row["observed_at"]
    decision_bar_index = _decision_bar_index(bars, str(decision_at))
    if decision_bar_index < 9:
        return None
    if row.get("outcome_observed_at"):
        try:
            if _et_naive(bars[-1]["time"]) < _et_naive(row["outcome_observed_at"]):
                return None
        except (TypeError, ValueError):
            return None
    return bars, decision_bar_index


def _example_payload(row: dict) -> dict | None:
    if not _eligible_recorded_row(row):
        return None
    category = _example_category(row)
    evidence = _chart_evidence(row)
    if evidence is None:
        return None
    bars, decision_index = evidence
    return {
        "example_id": str(row["candidate_id"]), "strategy_id": row["strategy_id"],
        "strategy_version": _recorded_strategy_version(row), "ticker": row["ticker"],
        "observed_at": row["observed_at"], "trigger_bar": row.get("trigger_bar"),
        "direction": row.get("direction"), "confidence": row.get("confidence"), "category": category,
        "outcome": row.get("final_outcome"), "gate_reason": row.get("gate_reason"),
        "gate_detail": row.get("gate_detail"), "directional_move_pct": row.get("directional_move_pct"),
        "direction_correct": row.get("direction_correct"), "outcome_observed_at": row.get("outcome_observed_at"),
        "bars": bars, "decision_bar_index": decision_index, "coach": _coach_copy(row, category),
        "provenance": "scanner_candle_observations + shadow_candidates",
        "episode_size": row.get("episode_size", 1), "practice_eligible": _practice_eligible(row, category),
        "source_revision": _source_revision(row),
    }


def _source_revision(row: dict) -> str:
    fields = ("final_outcome", "gate_reason", "gate_detail", "resolved_at",
              "directional_move_pct", "direction_correct", "outcome_observed_at", "episode_size")
    return json.dumps([row.get(field) for field in fields], default=str, separators=(",", ":"))


def _sync_curated_examples() -> int:
    """Durably publish only real, chart-complete examples, capped to the declared mix."""
    from database import get_conn
    now = datetime.now(_ET).isoformat()
    with get_conn() as conn:
        existing = {row["candidate_id"]: json.loads(row["evidence_json"]) for row in conn.execute(
            "SELECT candidate_id,evidence_json FROM learning_examples"
        ).fetchall()}
    selected: dict[tuple[str, str], int] = Counter()
    payloads: list[tuple[dict, int]] = []
    for row in _collapse_independent_episodes(_candidate_rows(limit=5000)):
        cached = existing.get(str(row.get("candidate_id")))
        payload = cached if cached and cached.get("source_revision") == _source_revision(row) else _example_payload(row)
        if payload is None:
            continue
        key = (payload["strategy_id"], payload["category"])
        quota_eligible = payload["category"] != "rejected_missing_condition" or payload["practice_eligible"]
        publish = int(quota_eligible and selected[key] < CATEGORY_TARGETS[payload["category"]])
        if publish:
            selected[key] += 1
        payloads.append((payload, publish))
    with get_conn() as conn:
        conn.execute("UPDATE learning_examples SET published=0,current_episode=0")
        for item, publish in payloads:
            conn.execute(
                """INSERT INTO learning_examples
                   (example_id,candidate_id,strategy_id,strategy_version,ticker,category,curated_at,evidence_json,published,current_episode)
                   VALUES (?,?,?,?,?,?,?,?,?,1) ON CONFLICT(candidate_id) DO UPDATE SET
                   category=excluded.category, curated_at=excluded.curated_at,
                   evidence_json=excluded.evidence_json, published=excluded.published,current_episode=1""",
                (item["example_id"], item["example_id"], item["strategy_id"], item["strategy_version"],
                 item["ticker"], item["category"], now, json.dumps(item, default=str), publish),
            )
    return sum(publish for _, publish in payloads)


def _expected_answers(example: dict) -> set[str]:
    if example["category"] in {"rejected_missing_condition", "false_breakout_or_chop"}:
        return {"reject"}
    if example["category"] == "ambiguous_no_trade":
        return {"wait", "reject"}
    return {"call" if str(example.get("direction")).lower() == "bullish" else "put"}


class PracticeStart(BaseModel):
    strategy_id: str
    ticker: str | None = None
    version: str | None = None


class PracticeAnswer(BaseModel):
    answer: Literal["call", "put", "wait", "reject"]


class CoachQuestion(BaseModel):
    example_id: str
    session_id: str
    question: str = Field(min_length=2, max_length=500)


def _practice_public_payload(example: dict) -> dict:
    cutoff = int(example["decision_bar_index"]) + 1
    return {
        "example_id": example["example_id"], "strategy_id": example["strategy_id"],
        "strategy_version": example["strategy_version"], "ticker": example["ticker"],
        "observed_at": example["observed_at"], "bars": example["bars"][:cutoff],
        "decision_bar_index": cutoff - 1,
        "prompt": "Enter in the visible setup direction, wait for confirmation, or reject the setup.",
    }


@router.get("/catalog")
def learning_catalog() -> dict:
    from database import get_conn
    counts: dict[str, Counter] = {strategy_id: Counter() for strategy_id in REVIEWED_STRATEGIES}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT strategy_id,category,COUNT(*) count FROM learning_examples WHERE published=1 GROUP BY strategy_id,category"
        ).fetchall()
    for row in rows:
        if row["strategy_id"] in counts:
            counts[row["strategy_id"]][row["category"]] = int(row["count"])
    strategies = []
    for strategy_id, rule in REVIEWED_STRATEGIES.items():
        category_counts = {key: counts[strategy_id][key] for key in CATEGORY_TARGETS}
        strategies.append({
            "strategy_id": strategy_id,
            "display_name": rule.display_name,
            "version": rule.version,
            "tickers": sorted(rule.tickers),
            "target": sum(CATEGORY_TARGETS.values()),
            "curated_examples": sum(category_counts.values()),
            "categories": category_counts,
            "category_targets": CATEGORY_TARGETS,
        })
    return {
        "strategies": strategies,
        "grounding": "Recorded account-scoped scanner episodes and one-minute candles only.",
        "order_authority": False,
    }


@router.get("/examples")
def learning_examples(
    strategy_id: str = Query(...),
    category: ExampleCategory | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    if strategy_id not in REVIEWED_STRATEGIES:
        raise HTTPException(status_code=404, detail="Unknown reviewed strategy")
    examples = []
    for row in _collapse_independent_episodes(_candidate_rows(strategy_id, limit=1000)):
        payload = _example_payload(row)
        if payload is None:
            continue
        example_category = payload["category"]
        if category and example_category != category:
            continue
        examples.append(payload)
        if len(examples) >= limit:
            break
    return {"strategy_id": strategy_id, "examples": examples, "count": len(examples)}


@router.post("/practice/start")
def start_practice(body: PracticeStart) -> dict:
    from auth.context import get_current_user_id
    from database import get_conn
    if body.strategy_id not in REVIEWED_STRATEGIES:
        raise HTTPException(404, "Unknown reviewed strategy")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT evidence_json FROM learning_examples WHERE strategy_id=? AND published=1 ORDER BY RANDOM()",
            (body.strategy_id,),
        ).fetchall()
        eligible = [json.loads(row["evidence_json"]) for row in rows]
        scope, params = _account_scope()
        owned = {row[0] for row in conn.execute(
            'SELECT candidate_id FROM shadow_candidates WHERE '+scope, params)}
        eligible = [item for item in eligible if item['example_id'] in owned
                    and (not body.ticker or item['ticker'] == body.ticker.upper())
                    and (not body.version or item['strategy_version'] == body.version)]
        example = next((item for item in eligible if item.get("practice_eligible")), None)
        if not example:
            return {"status": "empty", "message": "No reviewed practice examples yet for this selection. Read the lesson or reference while the library is being built.",
                    "strategy_id": body.strategy_id, "ticker": body.ticker,
                    "version": body.version, "order_authority": False}
        session_id = secrets.token_urlsafe(24)
        created = datetime.now(_ET); expires = created + timedelta(minutes=30)
        conn.execute(
            "INSERT INTO learning_practice_sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, get_current_user_id(), example["example_id"],
             json.dumps(sorted(_expected_answers(example))), created.isoformat(), expires.isoformat(), None, None, None),
        )
    return {"session_id": session_id, "expires_at": expires.isoformat(),
            "example": _practice_public_payload(example)}


@router.post("/practice/{session_id}/answer")
def answer_practice(session_id: str, body: PracticeAnswer) -> dict:
    from auth.context import get_current_user_id
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute(
            """SELECT s.*, e.evidence_json FROM learning_practice_sessions s
               JOIN learning_examples e ON e.example_id=s.example_id
               WHERE s.session_id=? AND s.user_id=?""", (session_id, get_current_user_id()),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Practice session not found")
        if row["answered_at"]:
            raise HTTPException(409, "Practice session already answered")
        if datetime.now(_ET) > datetime.fromisoformat(row["expires_at"]):
            raise HTTPException(410, "Practice session expired")
        correct = body.answer in set(json.loads(row["expected_answer"]))
        conn.execute("UPDATE learning_practice_sessions SET answered_at=?,answer=?,correct=? WHERE session_id=?",
                     (datetime.now(_ET).isoformat(), body.answer, int(correct), session_id))
        example = json.loads(row["evidence_json"])
    return {"correct": correct, "answer": body.answer, "example": example}


@router.post("/coach/ask")
def ask_coach(body: CoachQuestion) -> dict:
    from auth.context import get_current_user_id
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute(
            """SELECT e.evidence_json FROM learning_examples e
               JOIN learning_practice_sessions s ON s.example_id=e.example_id
               WHERE e.example_id=? AND e.published=1 AND s.session_id=?
                 AND s.user_id=? AND s.answered_at IS NOT NULL""",
            (body.example_id, body.session_id, get_current_user_id()),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Learning example not found")
    example = json.loads(row["evidence_json"])
    question = body.question.lower()
    if any(word in question for word in ("outcome", "happen", "after", "result")):
        answer = example["coach"]["summary"]
    elif any(word in question for word in ("why", "reason", "reject", "wait")):
        answer = str(example.get("gate_detail") or example.get("gate_reason") or example["coach"]["prompt"])
    elif any(word in question for word in ("version", "strategy", "rule")):
        answer = f"This is {example['strategy_id']} version {example['strategy_version']}. {example['coach']['prompt']}"
    else:
        answer = example["coach"]["prompt"]
    return {"answer": f"{answer} [F1]", "citations": [{"id": "F1", "source": example["provenance"]}],
            "order_authority": False, "external_data_transfer": False}


def _ranker_examples() -> list[dict]:
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute("SELECT evidence_json FROM learning_examples WHERE current_episode=1").fetchall()
    return [item for item in (json.loads(row["evidence_json"]) for row in rows)
            if item.get("direction_correct") in (0, 1)]


@router.get("/ranker/status")
def learning_ranker_status() -> dict:
    from ai_reasoning.learning_ranker import ranker_status
    examples = _ranker_examples()
    return ranker_status(len(examples))


@router.post("/ranker/train")
def train_learning_ranker(request: Request) -> dict:
    if not bool(getattr(request.state, "is_admin", False)):
        raise HTTPException(403, "Administrator access required")
    from ai_reasoning.learning_ranker import train_shadow_model
    return train_shadow_model(_ranker_examples())


@router.post("/curation/refresh")
def refresh_learning_curation(request: Request) -> dict:
    if not bool(getattr(request.state, "is_admin", False)):
        raise HTTPException(403, "Administrator access required")
    return {"curated_examples": _sync_curated_examples(), "order_authority": False}
