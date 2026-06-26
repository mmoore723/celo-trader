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

from trading.state import LIVE_STATE, _now_et, _BOT_ROOT

logger = logging.getLogger("celo_trader.trading_logic")


def _refresh_session_pnl() -> float:
    """
    Recompute LIVE_STATE["session_pnl"] from the DB and immediately flush it
    to bot_state.json so the WebSocket picks up the correct value.

    Called by every close path that doesn't go through _close_position
    (panic_close_all, close_trade_by_id, _panic_close_all_positions).
    """
    from database import get_all_trades
    try:
        pnl = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=200)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
        LIVE_STATE["session_pnl"] = pnl
    except Exception as e:
        logger.warning("_refresh_session_pnl: DB query failed: %s", e)
        pnl = LIVE_STATE.get("session_pnl", 0.0)

    # Flush to bot_state.json so the WebSocket doesn't read a stale value
    try:
        _path = _BOT_ROOT / "bot_state.json"
        _state = {}
        if _path.exists():
            with open(_path) as _f:
                _state = json.load(_f)
        _state["session_pnl"] = pnl
        with open(_path, "w") as _f:
            json.dump(_state, _f)
    except Exception as e:
        logger.warning("_refresh_session_pnl: bot_state.json write failed: %s", e)

    return pnl


def close_trade_by_id(trade_id: int) -> dict:
    """
    Close ONE specific open trade by its database id, without touching any
    other open positions.  Used by the Trade Journal per-row "Close Position"
    button.

    Returns: {"ok": bool, "message": str, "pnl": float | None}
    """
    from broker import get_clients
    from database import log_event, close_trade, get_open_trades

    alpaca, tradier = get_clients()

    trade = next((t for t in get_open_trades() if t["id"] == trade_id), None)
    if trade is None:
        msg = f"Trade #{trade_id} is not currently open — nothing to close."
        logger.warning("close_trade_by_id: %s", msg)
        return {"ok": False, "message": msg, "pnl": None}

    # ── Get a live price for the exit record ──────────────────────────────────
    try:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote and quote.get("mid", 0) > 0:
            exit_price = quote["mid"]
            logger.info("close_trade_by_id [trade %s]: live mid price = $%.4f",
                         trade_id, exit_price)
        else:
            exit_price = trade["entry_price"]
            logger.warning("close_trade_by_id [trade %s]: could not fetch live "
                            "price — using entry price as exit price", trade_id)
    except Exception as e:
        exit_price = trade["entry_price"]
        logger.error("close_trade_by_id [trade %s]: quote fetch failed (%s) — "
                      "using entry price as exit price", trade_id, e)

    # ── Liquidate at the broker ────────────────────────────────────────────────
    closed_at_broker = False
    try:
        closed_at_broker = alpaca.close_position(trade["contract_symbol"])
    except Exception as e:
        logger.error("close_trade_by_id [trade %s]: broker close_position raised %s",
                      trade_id, e)

    if not closed_at_broker:
        msg = (f"Could not close {trade['contract_symbol']} at the broker — "
               f"the journal entry was NOT marked closed. Check the audit log "
               f"and try again.")
        log_event("ERROR", "trading_logic",
                  f"🔴 Trade Journal close failed for trade #{trade_id} "
                  f"({trade['contract_symbol']}) — position left open.")
        return {"ok": False, "message": msg, "pnl": None}

    # ── Update the database row ────────────────────────────────────────────────
    try:
        pnl = close_trade(
            trade_id    = trade["id"],
            exit_price  = exit_price,
            exit_time   = _now_et(),
            exit_reason = "manual_journal",
        )
    except Exception as e:
        logger.error("close_trade_by_id [trade %s]: close_trade() DB update "
                      "failed after broker close succeeded — manual DB fix "
                      "may be needed (%s)", trade_id, e)
        return {
            "ok": False,
            "message": (f"Closed {trade['contract_symbol']} at the broker, but "
                         f"FAILED to update the journal record (#{trade_id}). "
                         f"The position is closed at Alpaca — please refresh "
                         f"and check the journal manually."),
            "pnl": None,
        }

    log_event(
        "INFO", "trading_logic",
        f"🟡 Trade Journal — manually closed {trade.get('ticker', '?')} "
        f"{trade.get('option_type', 'option').upper()} (trade #{trade_id}) "
        f"@ ${exit_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}.",
    )

    # ── Update session P&L ────────────────────────────────────────────────────
    _refresh_session_pnl()

    # ── Clear per-position state ───────────────────────────────────────────────
    LIVE_STATE["positions"].pop(trade_id, None)
    _remaining_open            = get_open_trades()
    LIVE_STATE["open_trades"]  = _remaining_open
    LIVE_STATE["open_trade"]   = _remaining_open[0] if _remaining_open else None
    LIVE_STATE["status"]       = "in_trade" if _remaining_open else "scanning"

    # Remove from bot_state.json open_positions
    try:
        import json as _json_cb
        _state_path_cb = _BOT_ROOT / "bot_state.json"
        if _state_path_cb.exists():
            with open(_state_path_cb) as _f:
                _existing_cb = _json_cb.load(_f)
            _open_positions_cb = _existing_cb.get("open_positions") or {}
            _open_positions_cb.pop(str(trade_id), None)
            _existing_cb["open_positions"] = _open_positions_cb
            with open(_state_path_cb, "w") as _f:
                _json_cb.dump(_existing_cb, _f)
    except Exception:
        pass

    return {
        "ok": True,
        "message": (f"Closed {trade.get('ticker', '?')} {trade.get('option_type','')} "
                     f"@ ${exit_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}."),
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


def panic_close_all() -> None:
    """
    Emergency flatten — closes all broker positions and marks all open DB
    trades as closed.
    """
    from broker import get_clients
    from database import get_open_trades, close_trade
    from database import log_event

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
    LIVE_STATE["status"] = "halted"
    LIVE_STATE["open_trades"] = []
    LIVE_STATE["open_trade"]  = None
    LIVE_STATE["positions"]   = {}
    # Recompute and flush session_pnl — panic bypasses _close_position
    _refresh_session_pnl()
    log_event("WARNING", "trading_logic",
              "🔴 Emergency close triggered — all positions have been closed.")


def _panic_close_all_positions(alpaca: "AlpacaClient", tradier: "TradierClient") -> None:
    """
    Internal variant called by the kill-lock handler in loop.py.
    Closes all broker positions and marks any open DB trade(s) as force-closed.
    """
    from database import log_event, get_open_trades, close_trade

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
    LIVE_STATE["status"]       = "kill_locked"
    LIVE_STATE["open_trade"]   = None
    LIVE_STATE["open_trades"]  = []
    LIVE_STATE["positions"]    = {}
    # Recompute and flush session_pnl — kill-lock bypasses _close_position
    _refresh_session_pnl()
    log_event("CRITICAL", "trading_logic",
              "🔴 Daily loss limit hit — all positions closed. "
              "Trading is frozen for 24 hours to protect your account.")
