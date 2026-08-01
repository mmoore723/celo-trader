"""
signal_journal/write.py — log_signal_outcome(), the single write path for
"what happened to this signal."

Split out of the old single signal_journal.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

import logging
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
) -> None:
    ts = _now_et().isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO signal_journal
                   (ts, ticker, strategy_id, direction, confidence,
                    outcome, reason_code, reason_detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, ticker.upper(), strategy_id, direction, round(float(confidence), 4),
                 outcome, reason_code, reason_detail),
            )
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
