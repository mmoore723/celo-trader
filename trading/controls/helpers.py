"""
trading/controls/helpers.py — Shared per-user helpers used by every
control function in this package: user-id resolution and session P&L
refresh/flush.

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from trading.state import get_user_state

logger = logging.getLogger("celo_trader.trading_logic")


def _default_user_id() -> str:
    """
    Resolve the calling user the same way config.py does: read the
    request-scoped ContextVar set by api/middleware/auth.py, falling back to
    "admin" for background-thread/single-user code paths.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "admin"


def _refresh_session_pnl(user_id: str | None = None) -> float:
    """
    Recompute the given user's session_pnl from the DB and immediately flush
    it to that user's bot_state.json so the WebSocket picks up the correct
    value.

    Called by every close path that doesn't go through _close_position
    (panic_close_all, close_trade_by_id, _panic_close_all_positions).

    FIX: previously always read/wrote the global LIVE_STATE alias (admin's
    state) and the single shared root bot_state.json — any user's manual
    close/panic action recomputed and displayed ADMIN's P&L, not their own.
    """
    from config import get_bot_state_path
    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    from database import get_all_trades
    try:
        pnl = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=200, user_id=uid)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
        _US["session_pnl"] = pnl
    except Exception as e:
        logger.warning("_refresh_session_pnl[%s]: DB query failed: %s", uid, e)
        pnl = _US.get("session_pnl", 0.0)

    # Flush to this user's bot_state.json so the WebSocket doesn't read a stale value
    try:
        _path = get_bot_state_path(uid)
        _state = {}
        if _path.exists():
            with open(_path) as _f:
                _state = json.load(_f)
        _state["session_pnl"] = pnl
        with open(_path, "w") as _f:
            json.dump(_state, _f)
    except Exception as e:
        logger.warning("_refresh_session_pnl[%s]: bot_state.json write failed: %s", uid, e)

    return pnl
