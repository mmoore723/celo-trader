"""
api/routes/strategy_health.py — built-in strategy audit endpoints.

Replaces "run a diag_*.py script on EC2, screenshot the terminal" with a
dashboard that always has the latest answer, plus an on-demand re-run button.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/strategy-health", tags=["strategy-health"])
logger = logging.getLogger("celo_trader.api.strategy_health")


def _research_snapshot(days: int, start_date: str | None, end_date: str | None, *, allow_stale=False) -> dict:
    from api.research_snapshot import research_snapshot
    return research_snapshot(days, start_date=start_date, end_date=end_date, allow_stale=allow_stale)


@router.get("/scorecard")
def get_scorecard(days: int = 30) -> dict:
    """Read-only strategy evidence scorecard; no allocation decisions here."""
    from strategy_health.scorecard import build_scorecard
    return build_scorecard(days)


@router.get("/daily-scorecard")
def get_daily_scorecard(mode: str = "paper", date: str | None = None) -> dict:
    """Fast account-scoped session result and lifecycle evidence audit."""
    from config import get_settings
    from database import _conn_for_mode, _now_et
    from strategy_health.daily_scorecard import build_daily_scorecard
    from strategy_health.event_tape import build_event_tape

    trading_date = date or _now_et().date().isoformat()
    account_id = get_settings().get("active_broker_account_id") or None
    try:
        with _conn_for_mode(mode) as conn:
            tape = build_event_tape(conn, trading_date, mode, account_id)
        return build_daily_scorecard(
            tape,
            include_strategy_replay=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidate-scorecard")
def get_candidate_scorecard(days: int = 30) -> dict:
    """Evidence-only view of every raw paper candidate and its final gate."""
    from config import get_settings
    from database import get_conn, _now_et

    days = max(1, min(int(days), 365))
    cutoff = (_now_et() - timedelta(days=days)).isoformat()
    account_id = get_settings().get("active_broker_account_id") or None
    clauses = ["observed_at >= ?"]
    params: list[object] = [cutoff]
    if account_id:
        clauses.append("broker_account_id = ?")
        params.append(account_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT strategy_id, final_outcome, gate_reason, "
            "COUNT(*) AS count, SUM(CASE WHEN outcome_observed_at IS NOT NULL THEN 1 ELSE 0 END) AS measured, "
            "SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END) AS correct, "
            "AVG(directional_move_pct) AS avg_directional_move_pct, "
            "MIN(CASE WHEN outcome_observed_at IS NULL THEN outcome_due_at END) AS next_outcome_at "
            "FROM shadow_candidates WHERE " + " AND ".join(clauses) +
            " GROUP BY strategy_id, final_outcome, gate_reason",
            tuple(params),
        ).fetchall()
    by_strategy: dict[str, dict] = {}
    from config.strategy_catalog import reviewed_strategy_ids
    approved_ids = reviewed_strategy_ids()
    next_outcome_at: str | None = None

    def _evidence_bucket() -> dict:
        return {"candidates": 0, "measured": 0, "correct": 0, "move_parts": []}
    for row in rows:
        if row["strategy_id"] not in approved_ids:
            continue
        item = by_strategy.setdefault(row["strategy_id"], {
            "strategy_id": row["strategy_id"], "raw_candidates": 0,
            "entered": 0, "blocked": 0, "pending": 0, "observed_only": 0, "block_reasons": defaultdict(int),
            "measured": 0, "correct": 0, "avg_directional_move_parts": [],
            "outcome_evidence": {
                "observed_only": _evidence_bucket(),
                "blocked": _evidence_bucket(),
                "entered": _evidence_bucket(),
            },
        })
        count = int(row["count"])
        item["raw_candidates"] += count
        outcome = str(row["final_outcome"])
        if outcome in {"entered", "blocked", "pending", "observed_only"}:
            item[outcome] += count
        if outcome == "blocked":
            item["block_reasons"][row["gate_reason"] or "unknown"] += count
        item["measured"] += int(row["measured"] or 0)
        item["correct"] += int(row["correct"] or 0)
        due = row["next_outcome_at"]
        if due and (next_outcome_at is None or str(due) < next_outcome_at):
            next_outcome_at = str(due)
        if row["avg_directional_move_pct"] is not None and int(row["measured"] or 0):
            item["avg_directional_move_parts"].append((float(row["avg_directional_move_pct"]), int(row["measured"])))
        bucket = item["outcome_evidence"].get(outcome)
        if bucket is not None:
            measured = int(row["measured"] or 0)
            bucket["candidates"] += count
            bucket["measured"] += measured
            bucket["correct"] += int(row["correct"] or 0)
            if row["avg_directional_move_pct"] is not None and measured:
                bucket["move_parts"].append((float(row["avg_directional_move_pct"]), measured))
    strategies = []
    for item in by_strategy.values():
        item["block_reasons"] = dict(sorted(item["block_reasons"].items(), key=lambda pair: -pair[1]))
        weighted = sum(value * count for value, count in item.pop("avg_directional_move_parts"))
        item["directional_win_rate"] = round(item["correct"] / item["measured"] * 100, 1) if item["measured"] else None
        item["avg_directional_move_pct"] = round(weighted / item["measured"], 3) if item["measured"] else None
        for bucket in item["outcome_evidence"].values():
            weighted_bucket = sum(value * count for value, count in bucket.pop("move_parts"))
            bucket["directional_win_rate"] = round(bucket["correct"] / bucket["measured"] * 100, 1) if bucket["measured"] else None
            bucket["avg_directional_move_pct"] = round(weighted_bucket / bucket["measured"], 3) if bucket["measured"] else None
        strategies.append(item)
    return {
        "days": days, "account_scoped": bool(account_id),
        "total_candidates": sum(item["raw_candidates"] for item in strategies),
        "measured_candidates": sum(item["measured"] for item in strategies),
        "next_outcome_at": next_outcome_at,
        "note": "Every built-in strategy is observed in paper mode. ‘Observed only’ means it was never eligible to order. Measured results are the underlying's same-session 60-minute directional move—not option P&L or a virtual fill.",
        "strategies": sorted(strategies, key=lambda item: item["raw_candidates"], reverse=True),
    }


@router.get("/research-matrix")
def get_research_matrix(days: int = 90, start_date: str | None = None, end_date: str | None = None) -> dict:
    """Simple strategy-by-ticker results; this endpoint cannot place orders."""
    try:
        if days == 90 and start_date is None and end_date is None:
            from database import _now_et
            today = _now_et().date()
            start_date, end_date = (today - timedelta(days=89)).isoformat(), today.isoformat()
        return _research_snapshot(days, start_date, end_date, allow_stale=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/research-results")
def get_research_results(
    days: int = 90, start_date: str | None = None, end_date: str | None = None,
    page: int = 1, page_size: int = 24, ticker: str = "", strategy_id: str = "",
    result_filter: str = "results",
) -> dict:
    from strategy_health.research_analytics import build_results_page

    try:
        matrix = _research_snapshot(days, start_date, end_date, allow_stale=True)
        return build_results_page(
            matrix, page=max(1, page), page_size=max(1, min(page_size, 60)),
            ticker=ticker, strategy_id=strategy_id, result_filter=result_filter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/research-analytics")
def get_research_analytics(
    days: int = 90, start_date: str | None = None, end_date: str | None = None,
    tickers: str = "", statuses: str = "",
) -> dict:
    from strategy_health.research_analytics import build_analytics

    try:
        matrix = _research_snapshot(days, start_date, end_date, allow_stale=True)
        return build_analytics(
            matrix,
            tickers={item.strip().upper() for item in tickers.split(",") if item.strip()},
            statuses={item.strip() for item in statuses.split(",") if item.strip()},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/paper-research/qqq-opening")
def get_qqq_opening_research_scorecard() -> dict:
    """Quote-to-quote evidence for the isolated QQQ study; never a trade report."""
    from trading.observers.qqq_opening_downmove import scorecard
    return {
        "note": "Paper observation only: no order is sent. Option result assumes entry at ask and exit at bid.",
        **scorecard(),
    }


@router.get("/research/paid-tsla-v2-orb")
def get_paid_tsla_v2_orb_research() -> dict:
    """Reviewed paid-data study summary; informational only, never a trade control."""
    from strategy_health.paid_research_evidence import v2_orb_tsla_summary
    return v2_orb_tsla_summary()


@router.get("/research/paid-tsla-trend-progress")
def get_paid_tsla_trend_progress() -> dict:
    """Current local paid-data study status; informational only."""
    from strategy_health.paid_research_progress import tsla_trend_exit_progress
    return tsla_trend_exit_progress()


@router.get("/paper/v2-orb")
def get_v2_orb_paper_scorecard() -> dict:
    """Account-scoped prospective V2 paper evidence; never a trade control."""
    from config import get_settings
    from strategy_health.v2_orb_paper_scorecard import build_v2_orb_paper_scorecard
    return build_v2_orb_paper_scorecard(
        broker_account_id=get_settings().get("active_broker_account_id") or None,
    )


@router.get("/latest")
def get_latest() -> dict:
    from database import get_latest_strategy_audit
    audit = get_latest_strategy_audit()
    if audit is None:
        return {"available": False}
    return {"available": True, **audit}


@router.get("/history")
def get_history(limit: int = 30) -> dict:
    from database import get_strategy_audit_history
    return {"audits": get_strategy_audit_history(limit)}


@router.post("/run")
def run_now() -> dict:
    """
    On-demand re-run. Synchronous like /api/backtest — a single day's audit
    across ~8-10 tickers is fast (nothing like a multi-month backtest), so
    blocking the request is fine and simpler than adding background-job
    machinery for this.
    """
    try:
        from broker import get_clients
        from strategy_health.runner import run_daily_audit
        from database import get_latest_strategy_audit
        alpaca, _ = get_clients()
        run_daily_audit(alpaca)
        # Re-read from the DB rather than returning run_daily_audit()'s raw
        # return value directly — guarantees this response has the EXACT
        # same shape as GET /latest (nested "aggregate" key, audit_date,
        # tickers, etc). Two hand-built response shapes previously drifted
        # apart and crashed the frontend (shown.aggregate was undefined).
        audit = get_latest_strategy_audit()
        return {"ok": True, "available": audit is not None, **(audit or {})}
    except Exception as e:
        logger.exception("strategy_health on-demand run failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Weekly rollup (added 2026-07-20) ───────────────────────────────────────
# Separate from the daily audit above — same page, different time horizon.
# See strategy_health/weekly.py for what's aggregated and why this isn't a
# second parallel system: it reuses the daily audits already saved plus a
# fresh read of real closed trades, nothing re-fetched from the market.

@router.get("/weekly/latest")
def get_weekly_latest() -> dict:
    from database import get_latest_strategy_audit
    audit = get_latest_strategy_audit(audit_type="weekly")
    if audit is None:
        return {"available": False}
    return {"available": True, **audit}


@router.get("/weekly/history")
def get_weekly_history(limit: int = 12) -> dict:
    from database import get_strategy_audit_history
    return {"audits": get_strategy_audit_history(limit, audit_type="weekly")}


@router.post("/weekly/run")
def run_weekly_now() -> dict:
    """On-demand weekly review — no market-data fetch involved (unlike the
    daily audit), so this is fast: it's just DB reads + one Claude call."""
    try:
        from strategy_health.runner import run_weekly_review
        from database import get_latest_strategy_audit
        run_weekly_review()
        audit = get_latest_strategy_audit(audit_type="weekly")
        return {"ok": True, "available": audit is not None, **(audit or {})}
    except Exception as e:
        logger.exception("strategy_health weekly on-demand run failed")
        raise HTTPException(status_code=500, detail=str(e))
