"""Authoritative day-open equity resolution for account P&L displays."""

from __future__ import annotations

from typing import Any, Mapping


def _positive_amount(value: Any) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def resolve_day_start_balance(
    account: Mapping[str, Any] | None,
    *,
    current_equity: float,
    persisted_balance: Any = None,
) -> tuple[float, str]:
    """Return the best available opening equity and its evidence source.

    Alpaca exposes ``last_equity``, the broker's official prior-session close.
    It remains correct across intraday bot restarts, unlike a balance captured
    when the process happens to start. Brokers that do not expose prior-close
    equity retain the first persisted balance for the calendar date.
    """
    broker_previous_close = _positive_amount((account or {}).get("last_equity"))
    if broker_previous_close is not None:
        return round(broker_previous_close, 2), "broker_previous_close"

    persisted = _positive_amount(persisted_balance)
    if persisted is not None:
        return round(persisted, 2), "persisted_day_open"

    current = _positive_amount(current_equity) or 0.0
    return round(current, 2), "first_observed_equity"
