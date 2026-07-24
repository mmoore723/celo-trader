"""
api/routes/signals.py — read-only endpoints over signal_journal.

Added 2026-07-24 per explicit user request: "we need to refactor bot
thinking... lets discuss how to make it useful." bot.log is an unstructured
50MB/day dump and ai_reasoning_log only narrates realized entries/exits —
neither answers "why didn't the bot trade today." signal_journal (see
signal_journal.py) records every strategy signal's final outcome, entered
or blocked-with-reason, and these three endpoints back the Thinking panel's
new summary bar, filterable row list, and 7-day trend strip.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/signals", tags=["signals"])
logger = logging.getLogger("celo_trader.api.signals")


@router.get("/journal")
def get_journal(
    ticker: str | None = None,
    strategy: str | None = Query(None, description="e.g. VWAP_PB, TREND_CONT"),
    reason: str | None = Query(None, description="reason_code — see signal_journal.REASON_CODES"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Today's rows (ET calendar day), newest first, optionally filtered."""
    from signal_journal import get_todays_rows
    try:
        rows = get_todays_rows(ticker=ticker, strategy=strategy, reason=reason, limit=limit)
        return {"entries": rows, "count": len(rows)}
    except Exception as e:
        logger.exception("signal journal fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/summary")
def get_journal_summary() -> dict:
    """
    Today's breakdown: total signals, entered count, and a count per
    reason_code — backs the panel's top summary bar.
    """
    from signal_journal import get_todays_summary
    try:
        return get_todays_summary()
    except Exception as e:
        logger.exception("signal journal summary fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/trend")
def get_journal_trend(
    reason: str = Query(..., description="reason_code to trend — see signal_journal.REASON_CODES"),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    """Daily count of one reason_code over the trailing N days."""
    from signal_journal import get_trend
    try:
        points = get_trend(reason_code=reason, days=days)
        return {"reason": reason, "days": days, "points": points}
    except Exception as e:
        logger.exception("signal journal trend fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/reasons")
def get_reason_codes() -> dict:
    """Reference list of reason codes + human-readable labels, for the filter dropdown."""
    from signal_journal import REASON_CODES
    return {"reasons": REASON_CODES}
