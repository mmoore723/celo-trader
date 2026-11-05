"""
broker/tradier_orders.py — TradierOrdersMixin: options order submission and
upcoming-earnings lookup.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Tradier*Mixin classes
into TradierClient in broker/tradier_client.py.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

import requests

from database import log_event
from broker.common import _retry, _debounced_log

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

    def get_earnings(self, symbol: str) -> list[str] | None:
        """Return validated dates, or None when the calendar is unavailable.

        An explicit empty event list is distinct from missing or malformed data.
        No plan entitlement is inferred from an HTTP error. This method does not
        decide whether missing earnings data blocks an entry.
        """
        url = f"{self.base}/markets/fundamentals/calendars"
        reason = None
        dates = None
        try:
            r = requests.get(url, headers=self.headers, params={"symbols": symbol},
                             timeout=10, allow_redirects=False)
            if r.status_code != 200:
                reason = f"HTTP {r.status_code}"
            else:
                events = r.json()["security"]["calendar"]["event"]
                if isinstance(events, dict):
                    events = [events]
                if not isinstance(events, list) or any(not isinstance(e, dict) or not e.get("type") for e in events):
                    raise ValueError("Invalid calendar events")
                dates = []
                for event in events:
                    if event["type"] == "earnings":
                        value = event["date"]
                        date.fromisoformat(value)
                        dates.append(value)
        except requests.Timeout:
            reason = "request timeout"
        except requests.RequestException:
            reason = "request failed"
        except (ValueError, KeyError, TypeError):
            reason = "invalid or missing calendar data"
        if reason:
            dates = None
        statuses = getattr(self, "earnings_status", {})
        previous = statuses.get(symbol, {})
        statuses[symbol] = {
            "status": "unavailable" if reason else "available",
            "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source": "tradier/markets/fundamentals/calendars",
            "dates": dates,
        }
        self.earnings_status = statuses
        if reason:
            _debounced_log("WARNING", "broker.earnings",
                           f"[{symbol}] Earnings data unavailable ({reason}). "
                           "The earnings blackout cannot be verified. Current entry behavior is unchanged; "
                           "this is NOT confirmation of no earnings.")
        elif previous.get("status") == "unavailable":
            log_event("INFO", "broker.earnings", f"[{symbol}] Earnings calendar lookup recovered.")
        return dates
