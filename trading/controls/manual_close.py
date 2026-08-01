"""
trading/controls/manual_close.py — manual_close_position(): dashboard
"Close Position" button handler.

Split out of the old single trading/controls.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("celo_trader.trading_logic")


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
