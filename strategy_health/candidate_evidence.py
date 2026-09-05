"""Shared eligibility rules for prospective strategy evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping


MAX_SIGNAL_DELAY_SECONDS_BY_STRATEGY = {
    # Trigger bars store their opening timestamp. Five-minute rules become
    # actionable immediately after that candle closes.
    "V2_SPY_TREND_CONT": 390,
    "V2_SPY_AFTERNOON_FVG": 390,
    # One-minute rules become actionable immediately after that candle closes.
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": 150,
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": 150,
}
DEFAULT_MAX_SIGNAL_DELAY_SECONDS = 390


def _moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _value(row: Mapping[str, object] | object, key: str) -> object:
    if hasattr(row, "get"):
        return row.get(key)  # type: ignore[union-attr]
    return row[key]  # type: ignore[index]


def candidate_signal_is_timely(row: Mapping[str, object] | object) -> bool:
    """Reject restarted or replayed signals which were no longer actionable."""
    trigger_value = _value(row, "trigger_bar")
    if not trigger_value:
        return False
    observed = _moment(_value(row, "observed_at")).replace(tzinfo=None)
    trigger = _moment(trigger_value).replace(tzinfo=None)
    delay = (observed - trigger).total_seconds()
    maximum = MAX_SIGNAL_DELAY_SECONDS_BY_STRATEGY.get(
        str(_value(row, "strategy_id") or ""), DEFAULT_MAX_SIGNAL_DELAY_SECONDS,
    )
    return 0 <= delay <= maximum
