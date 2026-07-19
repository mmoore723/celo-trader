"""
trading/controls.py — Manual and emergency position control functions.

Functions:
  close_trade_by_id         — per-row journal close (Trade Journal button)
  manual_close_position     — closes all open positions (dashboard button)
  panic_close_all           — emergency flatten (public API)
  _panic_close_all_positions — internal variant called by kill-lock handler
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date

from trading.state import _now_et, get_user_state

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


def close_trade_by_id(trade_id: int, user_id: str | None = None) -> dict:
    """
    Close ONE specific open trade by its database id.

    Used by:
      - Trade Journal per-row "Close" button
      - Open Positions table "Close" button

    Strategy: use place_option_order(sell, position_intent="sell_to_close") —
    the same path the trading loop uses for all exits — instead of the
    DELETE /v2/positions endpoint, which fails silently for paper-trading
    options accounts. If the broker sell order is rejected or never confirms
    a fill, the DB record is LEFT OPEN and an error is returned (2026-07-16:
    previously this silently marked the DB trade closed even on a rejected
    order, causing a bot-DB-vs-broker mismatch — see position_intent fix).

    Returns: {"ok": bool, "message": str, "pnl": float | None}
    """
    from broker import get_clients
    from config import get_settings
    from database import log_event, close_trade, get_open_trades

    uid = user_id or _default_user_id()
    _US = get_user_state(uid)

    alpaca, tradier = get_clients()
    settings = get_settings()
    paper    = settings.get("paper_trading", True)

    trade = next((t for t in get_open_trades() if t["id"] == trade_id), None)
    if trade is None:
        msg = f"Trade #{trade_id} is not currently open — nothing to close."
        logger.warning("close_trade_by_id: %s", msg)
        return {"ok": False, "message": msg, "pnl": None}

    # ── Fetch a live exit price ───────────────────────────────────────────────
    exit_price = trade["entry_price"]
    try:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote and quote.get("mid", 0) > 0:
            exit_price = float(quote["mid"])
    except Exception as e:
        logger.warning("close_trade_by_id [%s]: quote fetch failed (%s) — "
                        "using entry price", trade_id, e)

    # ── Place a market sell order (same as _close_position) ───────────────────
    # This works for both paper and live accounts. The old DELETE-endpoint path
    # failed silently on paper trading options and blocked the DB close.
    #
    # FIX 2026-07-16: two bugs fixed together here.
    #   1. No position_intent was sent, so Alpaca could misclassify this as
    #      OPENING a new naked/cash-secured short instead of closing the
    #      existing long — the same bug that stalled a live XLE exit.
    #   2. broker_ok was set True right after the call regardless of whether
    #      `fill` came back None (order rejected/never confirmed) — since
    #      place_option_order() catches its own errors internally and
    #      returns None rather than raising, the except block below almost
    #      never actually fires on a real rejection. That meant a rejected
    #      order still marked the DB trade closed, silently reintroducing a
    #      bot-DB-vs-broker mismatch. broker_ok now only True when Alpaca
    #      actually confirmed a fill — mirrors the safe pattern already used
    #      in position_manager.py's _close_position (leave trade open, retry,
    #      never fake a close).
    fill_price = exit_price
    broker_ok  = False
    try:
        fill = alpaca.place_option_order(
            symbol          = trade["contract_symbol"],
            qty             = trade["contracts"],
            side            = "sell",
            order_type      = "market",
            position_intent = "sell_to_close",
        )
        broker_ok = fill is not None
        if fill and fill.get("filled_avg_price"):
            fill_price = float(fill["filled_avg_price"])
    except Exception as e:
        logger.warning(
            "close_trade_by_id [%s]: broker sell order failed (%s)", trade_id, e
        )
        broker_ok = False

    if not broker_ok:
        # FIX 2026-07-17: if Alpaca's rejection is its specific "no matching
        # position" signature, this trade never actually filled there in the
        # first place (a fabricated/never-filled entry) — no amount of
        # retrying the close (or the user re-clicking Close) will ever
        # succeed. Auto-reconcile at $0 P&L instead of leaving the user
        # stuck clicking a button that can never work.
        from broker import is_phantom_position_rejection
        if is_phantom_position_rejection(getattr(alpaca, "last_rejection_reason", None)):
            pnl = close_trade(
                trade_id             = trade["id"],
                exit_price           = trade["entry_price"],
                exit_time            = _now_et(),
                exit_reason          = "auto_reconciled_no_broker_position",
                confirmed_fill_price = trade["entry_price"],
            )
            log_event(
                "ERROR", "trading_logic",
                f"🔧 Trade #{trade_id} ({trade['contract_symbol']}) — Alpaca has no "
                f"matching position, meaning the entry never actually filled there. "
                f"Auto-closed at $0 P&L instead of leaving it stuck.",
            )
            _refresh_session_pnl(uid)
            return {
                "ok": True,
                "message": (f"{trade['contract_symbol']} was never actually filled at "
                            f"the broker — auto-closed at $0 P&L."),
                "pnl": pnl,
            }

        msg = (f"Could not place sell order for {trade['contract_symbol']} "
               f"at the broker — DB record NOT closed. Check the audit log.")
        log_event("ERROR", "trading_logic",
                  f"🔴 Manual close failed for trade #{trade_id}: broker sell order rejected.")
        return {"ok": False, "message": msg, "pnl": None}

    # ── Mark the DB row closed ────────────────────────────────────────────────
    try:
        pnl = close_trade(
            trade_id             = trade["id"],
            exit_price           = exit_price,
            exit_time            = _now_et(),
            exit_reason          = "manual_journal",
            confirmed_fill_price = fill_price,
        )
    except Exception as e:
        logger.error("close_trade_by_id [%s]: DB close_trade() failed: %s", trade_id, e)
        return {
            "ok": False,
            "message": (f"Sell order placed, but DB update failed for trade #{trade_id}. "
                        f"Check the journal manually."),
            "pnl": None,
        }

    log_event(
        "INFO", "trading_logic",
        f"🟡 {'[PAPER] ' if paper else ''}Manually closed {trade.get('ticker','?')} "
        f"{trade.get('option_type','option').upper()} (trade #{trade_id}) "
        f"@ ${fill_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}.",
    )

    # ── Refresh session P&L + this user's state ──────────────────────────────
    _refresh_session_pnl(uid)
    _US["positions"].pop(trade_id, None)
    _remaining_open      = get_open_trades()
    _US["open_trades"]   = _remaining_open
    _US["open_trade"]    = _remaining_open[0] if _remaining_open else None
    _US["status"]        = "in_trade" if _remaining_open else "scanning"

    # Remove from this user's bot_state.json open_positions
    try:
        from config import get_bot_state_path
        _state_path_cb = get_bot_state_path(uid)
        if _state_path_cb.exists():
            with open(_state_path_cb) as _f:
                _existing_cb = json.load(_f)
            _open_positions_cb = _existing_cb.get("open_positions") or {}
            _open_positions_cb.pop(str(trade_id), None)
            _existing_cb["open_positions"] = _open_positions_cb
            _existing_cb["session_pnl"]    = _US.get("session_pnl", 0.0)
            with open(_state_path_cb, "w") as _f:
                json.dump(_existing_cb, _f)
    except Exception:
        pass

    return {
        "ok": True,
        "message": (f"Closed {trade.get('ticker','?')} {trade.get('option_type','')} "
                    f"@ ${fill_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}."),
        "pnl": pnl,
    }


def manual_close_position() -> None:
    """
    Dashboard "Close Position" button handler.  Closes ALL currently-open
    trades (one at a time, each with its own live quote).
    """
    from broker import get_clients
    from database import get_open_trades
    from trading.position_manager import _close_position

    alpaca, tradier = get_clients()
    trades = get_open_trades()
    if not trades:
        logger.info("Manual close: no open position")
        return

    for trade in trades:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote and quote.get("mid", 0) > 0:
            exit_price = quote["mid"]
            logger.info("Manual close [trade %s]: live mid price = $%.4f", trade["id"], exit_price)
        else:
            exit_price = trade["entry_price"]
            logger.warning("Manual close [trade %s]: could not fetch live price — using entry price", trade["id"])

        _close_position(alpaca, trade, exit_price, reason="manual")


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
