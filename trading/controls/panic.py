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


def _flatten_with_confirmed_fills(broker, market, *, reason: str) -> bool:
    """Close tracked trades first so every local close uses a confirmed fill."""
    from database import get_open_trades
    from trading.position_manager.close import _close_position

    for trade in list(get_open_trades()):
        try:
            quote = market.get_option_quote(trade["contract_symbol"])
        except Exception:
            quote = None
        bid = float((quote or {}).get("bid") or 0)
        trigger = float((quote or {}).get("mid") or bid or trade.get("entry_price") or 0)
        _close_position(
            broker, trade, trigger, reason,
            bid_price=bid if bid > 0 else None,
            reference_quote=quote,
        )

    # A tracked row must remain open unless its exit order produced a confirmed
    # fill (or the broker explicitly proved the position never existed).
    if get_open_trades():
        return False

    # Flatten any broker position that predates/escaped the local journal, then
    # verify that the account is actually flat. These cannot be assigned a
    # fabricated local exit price because no matching local trade exists.
    remaining = [
        row for row in (broker.get_positions() or [])
        if int(float(row.get("qty") or row.get("quantity") or 0)) != 0
    ]
    if remaining and broker.close_all_positions() is False:
        return False
    if remaining:
        remaining = [
            row for row in (broker.get_positions() or [])
            if int(float(row.get("qty") or row.get("quantity") or 0)) != 0
        ]
    return not remaining


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
    from database import log_event

    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    broker, market = get_clients()
    if not _flatten_with_confirmed_fills(broker, market, reason="panic"):
        raise RuntimeError(
            "Broker did not confirm every emergency exit; unresolved trades remain open"
        )
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
    from database import log_event

    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    flattened = False
    try:
        flattened = _flatten_with_confirmed_fills(
            alpaca, tradier, reason="kill_lock_force_close",
        )
    except Exception as ex:
        logger.error("kill_lock_close_all failed: %s", ex)
    _US["status"]      = "kill_locked"
    if flattened:
        _US["open_trade"]  = None
        _US["open_trades"] = []
        _US["positions"]   = {}
    # Recompute and flush session_pnl — kill-lock bypasses _close_position
    _refresh_session_pnl(uid)
    log_event(
        "CRITICAL", "trading_logic",
        "🔴 Daily loss limit hit — all positions closed. Trading is frozen for 24 hours to protect your account."
        if flattened else
        "🔴 Daily loss limit hit, but one or more broker exits are unconfirmed. Trading is frozen; manual review is required.",
    )
