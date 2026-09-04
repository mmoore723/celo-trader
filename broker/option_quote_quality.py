"""Check provenance before an optional Alpaca quote can replace an order price."""
from datetime import datetime, timezone
import math


def opra_quote_problem(quote, symbol: str, *, now=None, maximum_age_seconds=120.0):
    """Return a reason to preserve the caller's prices, or None for usable OPRA.

    The age limit matches the existing exact-contract entry freshness check.
    This does not block an order or alter the strategy/risk-approved prices.
    """
    if not isinstance(quote, dict):
        return "quote_unavailable"
    if quote.get("feed") != "opra":
        return "modified_or_unknown_feed"
    if quote.get("symbol") != symbol.upper():
        return "different_contract"
    try:
        bid, ask = float(quote["bp"]), float(quote["ap"])
        if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
            return "invalid_bid_ask"
        stamp = datetime.fromisoformat(str(quote["t"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "timestamp_without_timezone"
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if not 0 <= age <= maximum_age_seconds:
            return "stale_or_future_timestamp"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "invalid_quote_or_timestamp"
    return None
