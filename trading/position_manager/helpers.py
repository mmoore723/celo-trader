"""
trading/position_manager/helpers.py — Shared small helpers used by both
manage.py (per-tick management) and close.py (exit execution).

Split out of trading/position_manager.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from typing import Optional

from trading.state import get_user_state, _now_et

logger = logging.getLogger("celo_trader.trading_logic")


def _snapshot_exit_annotations(ticker: str) -> Optional[str]:
    """
    Thin, defensive wrapper around trading.annotations.snapshot_annotations()
    for every close_trade() call site. Captures the bot's own chart
    annotations (BOS levels, exit markers, etc.) at the moment of exit so
    Journal replay can show why the trade closed, not just that it did.

    Never raises: a failed snapshot must never block closing a live trade.
    """
    if not ticker:
        return None
    try:
        from trading.annotations import snapshot_annotations  # noqa: PLC0415
        return snapshot_annotations(ticker)
    except Exception:
        logger.warning("Exit annotation snapshot failed for %s — trade will close with no new annotations", ticker, exc_info=True)
        return None


def _reconcile_if_phantom(alpaca: "AlpacaClient", trade: dict) -> bool:
    """
    Call right after an exit order comes back None (fill is None). If the
    rejection was Alpaca's specific "no matching position" signature, this
    trade was never actually opened at the broker — a fabricated/never-filled
    entry — and retrying the close will NEVER succeed no matter how many
    times we try. Auto-closes the DB row at $0 P&L instead of looping
    forever. Returns True if it reconciled (caller should stop, not fall
    through to the normal "stays open, will retry" path).

    FIX 2026-07-17: built after trade #163 (INTC $120 call, entered by the
    now-fixed paper-fill-fabrication bug) retried its exit every ~1s for
    hours straight, hammering Alpaca with a doomed sell_to_close order.
    """
    _US = get_user_state()
    from broker import is_phantom_position_rejection
    if not is_phantom_position_rejection(getattr(alpaca, "last_rejection_reason", None)):
        return False

    from database import close_trade, log_event, get_open_trades

    entry_px = trade.get("entry_price", 0) or 0
    close_trade(
        trade_id             = trade["id"],
        exit_price            = entry_px,
        exit_time             = _now_et(),
        exit_reason           = "auto_reconciled_no_broker_position",
        confirmed_fill_price  = entry_px,
        paper                 = trade.get("paper", True),
        annotations_json      = _snapshot_exit_annotations(trade.get("ticker", "")),
    )
    log_event(
        "ERROR", "trading_logic",
        f"🔧 [{trade.get('ticker', '?')}] {trade['contract_symbol']} — Alpaca has "
        f"no matching position for this trade, meaning the entry never actually "
        f"filled there. Auto-closed at $0 P&L instead of retrying forever. "
        f"Check Alpaca's Positions/Orders tabs if you want to verify.",
    )
    logger.error(
        "phantom_position_auto_reconciled",
        extra={
            "event": "phantom_position_auto_reconciled",
            "trade_id": trade["id"],
            "symbol": trade["contract_symbol"],
        },
    )
    _US["open_trades"] = get_open_trades()
    _US["open_trade"]  = _US["open_trades"][0] if _US["open_trades"] else None
    _US.get("positions", {}).pop(trade["id"], None)
    return True
