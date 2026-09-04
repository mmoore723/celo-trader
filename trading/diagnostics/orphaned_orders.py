"""
trading/diagnostics/orphaned_orders.py — _sweep_orphaned_orders: cancels
resting broker orders that aren't tied to any currently-open DB trade.

Split out of the old single trading/diagnostics.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("celo_trader.trading_logic")

def _sweep_orphaned_orders(alpaca: "AlpacaClient", open_trades: list) -> None:
    """
    Cancel any resting Alpaca order whose symbol doesn't belong to a
    currently-tracked open trade.
    """
    from database import log_event

    try:
        open_orders = alpaca.get_open_orders()
    except Exception as e:
        logger.warning("_sweep_orphaned_orders: get_open_orders failed: %s", e)
        return
    if not open_orders:
        return

    tracked_symbols = {t.get("contract_symbol") for t in open_trades}
    if getattr(type(alpaca), "durable_order_recovery", False):
        try:
            from broker.recovery import scope
            tracked_symbols.update(row["symbol"] for row in scope(alpaca).pending())
        except Exception:
            logger.warning("orphan sweep skipped: recovery ownership unavailable", exc_info=True)
            return
    for o in open_orders:
        _sym = o.get("symbol")
        if _sym in tracked_symbols:
            continue
        _oid = o.get("id", "")
        if alpaca.cancel_order(_oid):
            log_event(
                "WARNING", "reconciliation",
                f"🟡 Requested cancellation of an orphaned resting order for {_sym} "
                f"(order ID: {_oid[:8]}…) that wasn't tied to any open "
                f"position the bot is tracking. Awaiting broker confirmation."
            )
            logger.warning(
                "orphan_order_swept",
                extra={"event": "orphan_order_swept", "symbol": _sym, "order_id": _oid},
            )
