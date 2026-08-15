"""
broker/tradier_orders.py — TradierOrdersMixin: options order submission and
upcoming-earnings lookup.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Tradier*Mixin classes
into TradierClient in broker/tradier_client.py.
"""

import logging
from typing import Optional

import requests

from database import log_event
from broker.common import _retry

logger = logging.getLogger("celo_trader.broker")


class TradierOrdersMixin:

    # ── Orders (FIX M2b: retry wrapper) ──────────────────────────────────────

    def place_option_order(
        self,
        symbol: str,
        option_symbol: str,
        qty: int,
        side: str,          # 'buy_to_open' | 'sell_to_close'
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Place an options order through Tradier brokerage.
        Uses TRADIER_ACCOUNT_ID from config (was missing before — FIX applied).
        Wraps with retry so transient network issues don't drop orders.
        """
        if not getattr(self, "api_key", "") or not getattr(self, "account_id", ""):
            logger.warning(
                "Tradier key or account ID missing — order not sent. "
                "Set TRADIER_API_KEY and TRADIER_ACCOUNT_ID in .env"
            )
            return None

        payload = {
            "class":         "option",
            "symbol":        symbol,
            "option_symbol": option_symbol,
            "side":          side,
            "quantity":      str(qty),
            "type":          order_type,
            "duration":      "day",
        }
        if order_type == "limit" and limit_price:
            payload["price"] = str(round(limit_price, 2))

        url = f"{self.base}/accounts/{self.account_id}/orders"

        def call():
            r = requests.post(url, headers=self.headers, data=payload, timeout=10)
            r.raise_for_status()
            return r.json()

        try:
            data = _retry(call)
            _oid = (data.get("order", {}) or {}).get("id", "—")
            log_event("INFO", "broker.tradier",
                      f"🟢 [{symbol}] Order confirmed by Tradier — {side.upper()} "
                      f"{qty}× {option_symbol} (order ID: {_oid}).")
            logger.info(
                "order_placed",
                extra={
                    "event": "order_placed",
                    "broker": "tradier",
                    "symbol": symbol,
                    "option_symbol": option_symbol,
                    "side": side,
                    "qty": qty,
                    "order_type": order_type,
                    "limit_price": limit_price,
                },
            )
            return data
        except Exception as e:
            log_event("ERROR", "broker.tradier",
                      f"🔴 [{symbol}] Order submission failed — {type(e).__name__}. "
                      f"No position opened.")
            logger.error(
                "order_execution_failed",
                extra={
                    "event": "order_execution_failed",
                    "broker": "tradier",
                    "symbol": symbol,
                    "option_symbol": option_symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(e),
                },
            )
            return None

    # ── Earnings ──────────────────────────────────────────────────────────────

    def get_earnings(self, symbol: str) -> list[str]:
        """
        Return upcoming earnings dates for `symbol` from Tradier.

        The /markets/fundamentals/calendars endpoint is only available on
        paid Tradier plans — it returns 404 on free/sandbox keys.
        Any HTTP 4xx is treated as "endpoint unavailable" and returns an empty
        list silently (debug-level only) so the bot isn't flooded with warnings.
        """
        # Call directly (no _retry) — this endpoint returns 404 on free Tradier
        # plans and retrying it 3× just spams the log.
        try:
            url = f"{self.base}/markets/fundamentals/calendars"
            r   = requests.get(url, headers=self.headers,
                               params={"symbols": symbol}, timeout=10)
            if r.status_code == 404 or r.status_code == 403:
                # Endpoint not available on this plan — silent, no retries.
                return []
            r.raise_for_status()
            resp   = r.json() if r.text and r.text.strip() else {}
            events = resp.get("security", {}).get("calendar", {}).get("event", [])
            if isinstance(events, dict):
                events = [events]
            return [
                e.get("date") for e in events
                if e.get("type") == "earnings" and e.get("date")
            ]
        except requests.exceptions.HTTPError as exc:
            logger.debug("get_earnings(%s): HTTP %s — skipping", symbol, exc)
            return []
        except Exception:
            return []
