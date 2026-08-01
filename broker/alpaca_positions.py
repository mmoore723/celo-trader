"""
broker/alpaca_positions.py — AlpacaPositionsMixin: panic-close, single-
position close, and resting-order cleanup.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Alpaca*Mixin classes
into AlpacaClient in broker/alpaca_client.py.
"""

import logging
from typing import Optional

from database import log_event

logger = logging.getLogger("celo_trader.broker")


class AlpacaPositionsMixin:

    # ── Panic close (FIX M2: retry wrapper) ──────────────────────────────────

    def close_all_positions(self) -> None:
        """
        Panic button — liquidates everything. Retries 5 times so one network
        hiccup doesn't leave positions open.
        """
        try:
            self._delete(f"{self.base}/v2/positions")
            log_event("WARNING", "broker.alpaca",
                      "🔴 Emergency close triggered — all positions have been liquidated.")
            logger.warning("PANIC BUTTON: all positions closed")
        except Exception as e:
            log_event("CRITICAL", "broker.alpaca",
                      f"🔴 [Alpaca] Emergency close FAILED after multiple retries — "
                      f"positions may still be open! Manual action required. ({type(e).__name__})")
            logger.critical("close_all_positions failed after retries: %s", e)

    def get_positions(self) -> list[dict]:
        try:
            result = self._get(f"{self.base}/v2/positions")
            return result if isinstance(result, list) else []
        except Exception:
            return []

    # ── Single-position close (NEW 2026-06-15 — Trade Journal close button) ──
    # close_all_positions() above liquidates EVERYTHING (panic button). This
    # method closes just ONE position by its OCC option symbol, via
    # "Close Position" button so the user can close individual untracked/
    def close_position(self, symbol: str) -> bool:
        """
        Close a single open position by its OCC option symbol.
        Returns True if the close request succeeded, False otherwise.
        """
        if not symbol:
            return False
        try:
            self._delete(f"{self.base}/v2/positions/{symbol}")
            log_event("WARNING", "broker.alpaca",
                      f"🟡 Manually closed position {symbol} from the Trade Journal.")
            logger.warning("manual_position_close: %s", symbol)
            return True
        except Exception as e:
            log_event("ERROR", "broker.alpaca",
                      f"🔴 [{symbol}] Failed to close position from Trade Journal "
                      f"after multiple retries — it may still be open. ({type(e).__name__})")
            logger.error("close_position failed for %s: %s", symbol, e)
            return False

    # ── Orphaned-order cleanup (FIX 2026-06-15 ghost positions) ───────────────
    # On 2026-06-15 a 403 response to a /v2/orders POST was treated as "order
    # Order never placed (returned None) — nothing to reconcile.

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """
        Return all currently-open (resting) orders, optionally filtered to a
        single OCC option symbol. Returns [] on any error — callers should
        treat that as "unknown" rather than "definitely none", but an empty
        list is also the correct/expected steady-state result.
        """
        try:
            params = {"status": "open"}
            if symbol:
                params["symbols"] = symbol
            result = self._get(f"{self.base}/v2/orders", params=params)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning("get_open_orders failed: %s", e)
            return []

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a single resting order by ID. Returns True if the cancel
        request succeeded (Alpaca returns 204 No Content), False otherwise.
        """
        if not order_id:
            return False
        try:
            self._delete(f"{self.base}/v2/orders/{order_id}")
            logger.info("order_cancelled", extra={"event": "order_cancelled", "order_id": order_id})
            return True
        except Exception as e:
            logger.error(
                "order_cancel_failed",
                extra={"event": "order_cancel_failed", "order_id": order_id, "error": str(e)},
            )
            return False
