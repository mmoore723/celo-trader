"""
trading/controls/panic.py — panic_close_all() (public API, e.g. admin
route) and _panic_close_all_positions() (internal, called by the kill-lock
handler in trading/loop/inner.py).

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging

from trading.state import _now_et, get_user_state
from trading.controls.helpers import _default_user_id, _refresh_session_pnl

logger = logging.getLogger("celo_trader.trading_logic")


def panic_close_all(user_id: str | None = None) -> None:
    """
    Emergency flatten — closes all broker positions and marks all open DB
    trades as closed.

    FIX: previously always wrote the global LIVE_STATE alias (admin's state)
    — any user's panic button correctly closed THEIR OWN broker positions
    (broker/DB calls resolve per-user via the auth ContextVar already) but
    then displayed the "halted" status on admin's dashboard instead of theirs.
    """
    from broker import get_clients
    from database import get_open_trades, close_trade
    from database import log_event

    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    alpaca, _ = get_clients()
    alpaca.close_all_positions()
    trades = get_open_trades()
    for trade in trades:
        try:
            quote = __import__("broker").TradierClient().get_option_quote(trade["contract_symbol"])
            exit_px = quote["mid"] if quote else trade["entry_price"]
        except Exception:
            exit_px = trade["entry_price"]
        close_trade(trade["id"], exit_price=exit_px,
                    exit_time=_now_et(), exit_reason="panic")
    _US["status"]      = "halted"
    _US["open_trades"] = []
    _US["open_trade"]  = None
    _US["positions"]   = {}
    # Recompute and flush session_pnl — panic bypasses _close_position
    _refresh_session_pnl(uid)
    log_event("WARNING", "trading_logic",
              "🔴 Emergency close triggered — all positions have been closed.")


def _panic_close_all_positions(
    alpaca: "AlpacaClient", tradier: "TradierClient", user_id: str | None = None,
) -> None:
    """
    Internal variant called by the kill-lock handler in loop.py.
    Closes all broker positions and marks any open DB trade(s) as force-closed.
    """
    from database import log_event, get_open_trades, close_trade

    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    try:
        alpaca.close_all_positions()
    except Exception as ex:
        logger.error("kill_lock_close_all failed: %s", ex)
    trades = get_open_trades()
    for trade in trades:
        try:
            quote   = tradier.get_option_quote(trade["contract_symbol"])
            exit_px = quote["mid"] if quote else trade["entry_price"]
        except Exception:
            exit_px = trade["entry_price"]
        close_trade(
            trade["id"],
            exit_price  = exit_px,
            exit_time   = _now_et(),
            exit_reason = "kill_lock_force_close",
        )
    _US["status"]      = "kill_locked"
    _US["open_trade"]  = None
    _US["open_trades"] = []
    _US["positions"]   = {}
    # Recompute and flush session_pnl — kill-lock bypasses _close_position
    _refresh_session_pnl(uid)
    log_event("CRITICAL", "trading_logic",
              "🔴 Daily loss limit hit — all positions closed. "
              "Trading is frozen for 24 hours to protect your account.")
