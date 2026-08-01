"""
trading/controls/journal_close.py — close_trade_by_id(): per-row journal
close, used by the Trade Journal and Open Positions table "Close" buttons.

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Kept as one function — it's a single, real order-placement-and-DB-close
sequence with several sequential fallback branches (live quote fetch,
broker sell order, phantom-position auto-reconcile, DB close, state
cleanup) that all depend on each other's outcome; splitting it up would
mean threading several local variables (trade, exit_price, fill_price,
broker_ok) through function-call boundaries for no real benefit.
"""

from __future__ import annotations

import json
import logging

from trading.state import _now_et, get_user_state
from trading.controls.helpers import _default_user_id, _refresh_session_pnl

logger = logging.getLogger("celo_trader.trading_logic")


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
