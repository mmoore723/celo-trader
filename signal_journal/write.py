"""
signal_journal/write.py — log_signal_outcome(), the single write path for
"what happened to this signal."

Split out of the old single signal_journal.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

import logging
import json
from typing import Optional

from database import get_conn, _now_et

logger = logging.getLogger("celo_trader.signal_journal")


def log_signal_outcome(
    ticker: str,
    strategy_id: str,
    direction: str,
    confidence: float,
    outcome: str,                          # 'entered' | 'blocked'
    reason_code: Optional[str] = None,     # required when outcome='blocked'
    reason_detail: Optional[str] = None,   # human-readable specifics
    trade_id: Optional[int] = None,
    context: Optional[dict] = None,
    tier: str = "main",
) -> Optional[int]:
    """Persist one signal outcome and return its journal-row id.

    An ``entered`` record must point to the trade row that was created first.
    Returning the journal id allows the entry path to surface a failed
    write instead of silently presenting an unlinked trade as complete.
    """
    if outcome == "entered" and trade_id is None:
        logger.error(
            "signal_journal entered outcome missing trade_id: %s %s",
            ticker, strategy_id,
        )
        return None

    ts = _now_et().isoformat()
    journal_id: Optional[int] = None
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO signal_journal
                   (ts, ticker, strategy_id, direction, confidence,
                    outcome, reason_code, reason_detail, trade_id, context_json, tier)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, ticker.upper(), strategy_id, direction, round(float(confidence), 4),
                 outcome, reason_code, reason_detail, trade_id,
                 json.dumps(context, default=str, sort_keys=True) if context else None,
                 tier if tier in ("main", "opportunity") else "main"),
            )
            journal_id = int(cursor.lastrowid)
    except Exception as exc:
        # Non-fatal by design — see package docstring.
        logger.warning("log_signal_outcome: failed to persist (non-fatal): %s", exc)

    _evt = "SIGNAL_ENTERED" if outcome == "entered" else "SIGNAL_BLOCKED"
    _msg = f"{ticker} {direction} {strategy_id} {confidence:.0%}"
    if reason_detail:
        _msg += f" — {reason_detail}"
    _lvl = logging.INFO
    logger.log(
        _lvl, _msg,
        extra={
            "event":         _evt,
            "ticker":        ticker.upper(),
            "strategy_id":   strategy_id,
            "direction":     direction,
            "confidence":    round(float(confidence), 3),
            "outcome":       outcome,
            "reason_code":   reason_code,
            "reason_detail": reason_detail,
        },
    )
    return journal_id
