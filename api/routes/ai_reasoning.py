"""
api/routes/ai_reasoning.py — read-only endpoints over ai_reasoning_log.

Added 2026-07-20 per explicit user request: before trusting any AI-driven
narration or decision support (entry veto/resize), the user wants to see
the EXACT prompt sent and the EXACT raw response received for every call —
not a summary, a literal replay — so hallucination, prompt drift, or a
model change on Anthropic's side can be caught by inspection rather than
assumed away. Every row in ai_reasoning_log is written regardless of
success/failure (see database.log_ai_reasoning), so this is the complete
trail, not a highlight reel.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/ai-reasoning", tags=["ai-reasoning"])
logger = logging.getLogger("celo_trader.api.ai_reasoning")


@router.get("/log")
def get_log(
    limit: int = Query(100, ge=1, le=500),
    event_type: str | None = Query(None, description="entry_narration | exit_narration | entry_veto"),
    ticker: str | None = None,
    only_errors: bool = False,
) -> dict:
    from database import get_ai_reasoning_log
    try:
        rows = get_ai_reasoning_log(
            limit=limit, event_type=event_type, ticker=ticker, only_errors=only_errors,
        )
        return {"entries": rows, "count": len(rows)}
    except Exception as e:
        logger.exception("ai_reasoning log fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log/{entry_id}")
def get_log_entry(entry_id: int) -> dict:
    from database import get_ai_reasoning_entry
    row = get_ai_reasoning_entry(entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return row
