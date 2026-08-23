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
import sqlite3
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from config.strategy_catalog import REVIEWED_STRATEGIES


router = APIRouter(prefix="/api/learning", tags=["learning"])
logger = logging.getLogger("celo_trader.api.learning")

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
    if measured and int(direction_correct or 0) == 1:
        return "clean_win"
    if measured and int(direction_correct or 0) == 0:
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


@router.get("/catalog")
def learning_catalog() -> dict:
    counts: dict[str, Counter] = {strategy_id: Counter() for strategy_id in REVIEWED_STRATEGIES}
    for row in _collapse_independent_episodes(_candidate_rows(limit=5000)):
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id in counts and _eligible_recorded_row(row):
            counts[strategy_id][_example_category(row)] += 1
    strategies = []
    for strategy_id, rule in REVIEWED_STRATEGIES.items():
        category_counts = {key: counts[strategy_id][key] for key in CATEGORY_TARGETS}
        strategies.append({
            "strategy_id": strategy_id,
            "display_name": rule.display_name,
            "version": rule.version,
            "tickers": sorted(rule.tickers),
            "target": sum(CATEGORY_TARGETS.values()),
            "candidate_episodes": sum(category_counts.values()),
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
        if not _eligible_recorded_row(row):
            continue
        example_category = _example_category(row)
        if category and example_category != category:
            continue
        chart_evidence = _chart_evidence(row)
        if chart_evidence is None:
            continue
        bars, decision_bar_index = chart_evidence
        coach = _coach_copy(row, example_category)
        examples.append({
            "example_id": str(row["candidate_id"]),
            "strategy_id": strategy_id,
            "strategy_version": _recorded_strategy_version(row),
            "ticker": row["ticker"],
            "observed_at": row["observed_at"],
            "trigger_bar": row.get("trigger_bar"),
            "direction": row.get("direction"),
            "category": example_category,
            "outcome": row.get("final_outcome"),
            "gate_reason": row.get("gate_reason"),
            "gate_detail": row.get("gate_detail"),
            "directional_move_pct": row.get("directional_move_pct"),
            "direction_correct": row.get("direction_correct"),
            "outcome_observed_at": row.get("outcome_observed_at"),
            "bars": bars,
            "decision_bar_index": decision_bar_index,
            "coach": coach,
            "provenance": "scanner_candle_observations + shadow_candidates",
            "episode_size": row.get("episode_size", 1),
            "practice_eligible": _practice_eligible(row, example_category),
        })
        if len(examples) >= limit:
            break
    return {"strategy_id": strategy_id, "examples": examples, "count": len(examples)}
