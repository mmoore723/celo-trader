"""Validate option order intent before broker submission or recovery enrollment."""
import math


def validate_option_price(order_type, limit_price):
    if order_type not in {"limit", "market"}:
        raise ValueError("Unsupported option order type")
    if order_type == "market":
        return limit_price
    message = "Option limit orders require a positive finite price"
    if isinstance(limit_price, bool) or limit_price is None:
        raise ValueError(message)
    try:
        price = float(limit_price)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(price) or round(price, 2) <= 0:
        raise ValueError(message)
    return price
