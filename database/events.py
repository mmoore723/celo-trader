"""
database/events.py — system_events audit log (log_event) and the AI
reasoning replay log (log_ai_reasoning, get_ai_reasoning_log,
get_ai_reasoning_entry).

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging
import sqlite3
from typing import Optional

from database.connection import get_conn
from database.helpers import _now_et

logger = logging.getLogger("celo_trader.database")

# ── System events ─────────────────────────────────────────────────────────────

def log_event(level: str, component: str, message: str) -> None:
    """
    Persist a system event to both:
      1. SQLite system_events table  (audit trail, Trade Journal)
      2. bot.log via Python logger   (THINKING panel in the dashboard)

    Previously log_event only wrote to SQLite, so all strategy decision
    messages ("No trade setup found", "Outside trading hours", entry/exit
    narratives, etc.) were invisible to the THINKING panel which reads bot.log.
    The dual-write here fixes that without changing any call sites.
    """
    # 1. Persist to SQLite
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO system_events (ts, level, component, message) VALUES (?, ?, ?, ?)",
                (_now_et().isoformat(), level, component, message),
            )
    except sqlite3.Error:
        logger.exception('System event database write failed; retaining event in application log')

    # 2. Mirror to bot.log so WebSocket → THINKING panel can display it.
    # Use component as the logger name (e.g. "celo_trader.bar_eval") so the
    # frontend's network/thinking tab split works correctly — bar_eval and
    # trading_logic messages land in THINKING, not Network.
    import logging as _logging
    _evt_logger = _logging.getLogger(f"celo_trader.{component}")
    _lvl = level.upper()
    if _lvl == "ERROR":
        _evt_logger.error(message)
    elif _lvl in ("WARNING", "WARN"):
        _evt_logger.warning(message)
    else:
        _evt_logger.info(message)


# ── AI reasoning replay log ───────────────────────────────────────────────────

def log_ai_reasoning(
    event_type: str,
    ticker: str,
    feature_snapshot: dict,
    prompt: str,
    response_text: Optional[str] = None,
    latency_ms: Optional[int] = None,
    model: Optional[str] = None,
    error: Optional[str] = None,
    trade_id: Optional[int] = None,
    applied: bool = False,
) -> None:
    """
    Persist one AI reasoning call to ai_reasoning_log — narration today
    (event_type='entry_narration'/'exit_narration'), decision-support later
    (event_type='entry_veto').

    Called on EVERY call attempt, success or not — a timeout or API error
    still gets a row (error set, response_text NULL) so the replay trail the
    user asked for is complete, not just a highlight reel of the calls that
    worked. Never raises: a logging failure must never be allowed to affect
    the trade the call was about.
    """
    import json as _json
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO ai_reasoning_log
                   (ts, event_type, ticker, trade_id, feature_snapshot_json,
                    prompt, response_text, latency_ms, model, error, applied)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _now_et().isoformat(), event_type, ticker, trade_id,
                    _json.dumps(feature_snapshot, default=str),
                    prompt, response_text, latency_ms, model, error,
                    1 if applied else 0,
                ),
            )
    except Exception as exc:
        # Non-fatal by design — see module docstring in ai_reasoning/client.py
        # for why nothing in this layer is allowed to raise into the trading loop.
        logger.warning("log_ai_reasoning: failed to persist (non-fatal): %s", exc)


def get_ai_reasoning_log(
    limit: int = 100,
    event_type: Optional[str] = None,
    ticker: Optional[str] = None,
    only_errors: bool = False,
) -> list[dict]:
    """
    Read back the full prompt/response replay trail from ai_reasoning_log,
    newest first. Added 2026-07-20 per explicit user request — the table has
    logged every AI call since phase 1 shipped, but nothing ever read it back
    for the user to audit. Every row includes the exact prompt text sent and
    the raw model response, so this is a literal replay, not a summary —
    the point is verifying the model isn't hallucinating or being steered by
    a bad prompt, not trusting a paraphrase of what it said.
    """
    with get_conn() as conn:
        query = "SELECT * FROM ai_reasoning_log WHERE 1=1"
        params: list = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        if only_errors:
            query += " AND error IS NOT NULL"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_ai_reasoning_entry(entry_id: int) -> Optional[dict]:
    """Single full row by id — used for the expanded prompt/response view."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ai_reasoning_log WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None
