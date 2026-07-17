"""
api/routes/strategy_health.py — built-in strategy audit endpoints.

Replaces "run a diag_*.py script on EC2, screenshot the terminal" with a
dashboard that always has the latest answer, plus an on-demand re-run button.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/strategy-health", tags=["strategy-health"])
logger = logging.getLogger("celo_trader.api.strategy_health")


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
        alpaca, _ = get_clients()
        result = run_daily_audit(alpaca)
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("strategy_health on-demand run failed")
        raise HTTPException(status_code=500, detail=str(e))
