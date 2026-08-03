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


@router.get("/scorecard")
def get_scorecard(days: int = 30) -> dict:
    """Read-only strategy evidence scorecard; no allocation decisions here."""
    from strategy_health.scorecard import build_scorecard
    return build_scorecard(days)


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
            "SELECT strategy_id, final_outcome, gate_reason, COUNT(*) AS count "
            "FROM shadow_candidates WHERE " + " AND ".join(clauses) +
            " GROUP BY strategy_id, final_outcome, gate_reason",
            tuple(params),
        ).fetchall()
    by_strategy: dict[str, dict] = {}
    for row in rows:
        item = by_strategy.setdefault(row["strategy_id"], {
            "strategy_id": row["strategy_id"], "raw_candidates": 0,
            "entered": 0, "blocked": 0, "pending": 0, "block_reasons": defaultdict(int),
        })
        count = int(row["count"])
        item["raw_candidates"] += count
        outcome = str(row["final_outcome"])
        if outcome in {"entered", "blocked", "pending"}:
            item[outcome] += count
        if outcome == "blocked":
            item["block_reasons"][row["gate_reason"] or "unknown"] += count
    strategies = []
    for item in by_strategy.values():
        item["block_reasons"] = dict(sorted(item["block_reasons"].items(), key=lambda pair: -pair[1]))
        strategies.append(item)
    return {
        "days": days, "account_scoped": bool(account_id),
        "note": "Evidence only: a blocked candidate has not yet been virtual-filled or assigned P&L.",
        "strategies": sorted(strategies, key=lambda item: item["raw_candidates"], reverse=True),
    }


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
