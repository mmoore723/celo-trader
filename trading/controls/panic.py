"""
trading/controls/panic.py — panic_close_all() (public API, e.g. admin
route) and _panic_close_all_positions() (internal, called by the kill-lock
handler in trading/loop/inner.py).

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
import math
import time

from trading.state import _now_et, get_user_state
from trading.controls.helpers import _default_user_id, _refresh_session_pnl

logger = logging.getLogger("celo_trader.trading_logic")


def _flatten_with_confirmed_fills(broker, market, *, reason: str) -> bool:
    """Close tracked trades first so every local close uses a confirmed fill."""
    from database import get_open_trades
    from trading.position_manager.close import _close_position

    from broker.recovery import reconcile_orders
    pending_symbols = reconcile_orders(broker)

    for trade in list(get_open_trades()):
        if trade["contract_symbol"] in pending_symbols:
            continue  # Other confirmed positions can still be closed safely.
        try:
            quote = market.get_option_quote(trade["contract_symbol"])
        except Exception:
            quote = None
        bid = float((quote or {}).get("bid") or 0)
        trigger = float((quote or {}).get("mid") or bid or trade.get("entry_price") or 0)
        try:
            _close_position(
                broker, trade, trigger, reason,
                bid_price=bid if bid > 0 else None,
                reference_quote=quote,
            )
        except Exception:
            logger.exception("Emergency close requires reconciliation for %s", trade["contract_symbol"])

    # A tracked row must remain open unless its exit order produced a confirmed
    # fill (or the broker explicitly proved the position never existed).
    if get_open_trades() or pending_symbols:
        return False

    # Flatten any broker position that predates/escaped the local journal, then
    # verify that the account is actually flat. These cannot be assigned a
    # fabricated local exit price because no matching local trade exists.
    remaining = _confirmed_positions(broker)
    working = broker.get_open_orders()
    if not isinstance(working, list) or working:
        # Do not cancel unrelated orders or repeat a broker-wide close while
        # an order is still working. Reconciliation must resolve it first.
        return False
    if remaining and broker.close_all_positions() is False:
        return False
    if remaining:
        remaining = _confirmed_positions(broker)
    final_orders = broker.get_open_orders()
    return not remaining and isinstance(final_orders, list) and not final_orders


def _confirmed_positions(broker) -> list:
    rows = broker.get_positions()
    if not isinstance(rows, list):
        raise ValueError("Broker positions snapshot unavailable")
    remaining = []
    for row in rows:
        qty = float(row.get("qty", row.get("quantity")))
        if not math.isfinite(qty):
            raise ValueError("Invalid broker position quantity")
        if qty != 0:
            remaining.append(row)
    return remaining


def service_daily_loss_halt(broker, market, *, user_id: str) -> bool:
    """Retry the existing close/recovery path without a 24-hour blind sleep."""
    from risk.kill_lock import flatten_pending, confirm_flattened
    state = get_user_state(user_id)
    if not flatten_pending():
        state["daily_loss_close_pending"] = False
        return False
    first_notice = not state.get("daily_loss_close_pending")
    state["daily_loss_close_pending"] = True
    state["status"] = "kill_locked"
    now = time.monotonic()
    if now < state.get("_loss_close_retry_at", 0):
        return True
    state["_loss_close_retry_at"] = now + 30
    if first_notice:
        try:
            from alerts import send_alert
            send_alert("DAILY LOSS LIMIT — ENTRIES BLOCKED",
                       "Closing bot positions; unconfirmed exits will be retried. Check broker confirmations.")
        except Exception:
            logger.exception("Daily-loss alert failed; continuing close recovery")
    if _panic_close_all_positions(broker, market, user_id=user_id):
        confirm_flattened()
        state["daily_loss_close_pending"] = False
        return False
    return True


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
) -> bool:
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
    try:
        _refresh_session_pnl(uid)
        log_event(
            "CRITICAL", "trading_logic",
            "Daily loss halt — broker confirmed flat. Entries remain locked until the halt expires."
            if flattened else
            "Daily loss halt — exits unconfirmed. Entries blocked; reconciliation will retry. Untracked orders may need manual review.",
        )
    except Exception:
        logger.exception("Could not update daily-loss close diagnostics")
    return flattened
