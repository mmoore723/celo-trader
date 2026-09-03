"""
trading/controls/helpers.py — Shared per-user helpers used by every
control function in this package: user-id resolution and session P&L
refresh/flush.

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging

from trading.state import _now_et, get_user_state

logger = logging.getLogger("celo_trader.trading_logic")


def _default_user_id() -> str:
    """
    Resolve the calling user the same way config.py does: read the
    request-scoped ContextVar set by api/middleware/auth.py. Unscoped service
    work is isolated under the system tenant rather than inheriting admin.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "system"


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
    from config import get_bot_state_path, atomic_update_json
    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    from database import get_all_trades
    try:
        mode = str(_US.get("mode") or "paper").lower()
        if mode not in {"paper", "live"}:
            mode = "paper"
        pnl = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(
                limit=200,
                mode=mode,
                broker_account_id=_US.get("broker_account_id"),
                user_id=uid,
            )
            if (t.get("exit_time") or "")[:10] == _now_et().date().isoformat()
        )
        _US["session_pnl"] = pnl
    except Exception as e:
        logger.warning("_refresh_session_pnl[%s]: DB query failed: %s", uid, e)
        pnl = _US.get("session_pnl", 0.0)

    # Flush to this user's bot_state.json so the WebSocket doesn't read a stale value
    try:
        _path = get_bot_state_path(uid)
        atomic_update_json(
            _path,
            lambda state: {**state, "session_pnl": pnl},
        )
    except Exception as e:
        logger.warning("_refresh_session_pnl[%s]: bot_state.json write failed: %s", uid, e)

    return pnl
