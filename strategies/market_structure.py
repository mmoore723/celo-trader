"""Small, production-safe market-structure primitives.

These calculations are shared by the reviewed live strategies.  They live
with production strategies rather than the research engine so a deployment
never depends on paid-data tooling, archived datasets, or experiment scripts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Mapping, Sequence

from strategies.price_action_context import describe_price_action


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Bar:
    """A completed OHLCV bar used only for deterministic calculations."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low must contain open and close")


@dataclass(frozen=True)
class StructureSignal:
    side: Side
    timestamp: datetime
    entry_reference: float
    stop: float
    target: float
    features: Mapping[str, float | str | bool] = field(default_factory=dict)


def resample_regular_session(
    bars: Sequence[Bar], source_minutes: int, target_minutes: int,
) -> tuple[Bar, ...]:
    """Build complete session-anchored bars and discard incomplete buckets."""
    if source_minutes < 1 or target_minutes < source_minutes or target_minutes % source_minutes:
        raise ValueError("target_minutes must be a whole multiple of source_minutes")
    if target_minutes == source_minutes:
        return tuple(bars)
    expected = target_minutes // source_minutes
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        session_start = bar.timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed = int((bar.timestamp - session_start).total_seconds() // 60)
        if elapsed < 0:
            continue
        bucket_time = session_start + timedelta(minutes=(elapsed // target_minutes) * target_minutes)
        buckets.setdefault(bucket_time, []).append(bar)
    output: list[Bar] = []
    for bucket_time in sorted(buckets):
        group = buckets[bucket_time]
        expected_times = [bucket_time + timedelta(minutes=source_minutes * index) for index in range(expected)]
        if len(group) != expected or [bar.timestamp for bar in group] != expected_times:
            continue
        output.append(Bar(
            bucket_time, group[0].open, max(bar.high for bar in group),
            min(bar.low for bar in group), group[-1].close,
            sum(bar.volume for bar in group),
        ))
    return tuple(output)


def _ema(values: Sequence[float], length: int) -> float:
    value = values[0]
    alpha = 2.0 / (length + 1.0)
    for item in values[1:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _atr(bars: Sequence[Bar], length: int) -> float:
    relevant = bars[-(length + 1):]
    ranges = [
        max(bar.high - bar.low, abs(bar.high - prior.close), abs(bar.low - prior.close))
        for prior, bar in zip(relevant, relevant[1:])
    ]
    return sum(ranges) / len(ranges)


@dataclass(frozen=True)
class TrendContinuationConfig:
    fast_ema: int = 10
    slow_ema: int = 20
    breakout_bars: int = 8
    atr_bars: int = 14
    stop_atr_multiple: float = 1.0
    reward_risk: float = 2.0


class TrendContinuation:
    """Directional setup used by the reviewed Trend Continuation adapters."""

    def __init__(self, config: TrendContinuationConfig = TrendContinuationConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> StructureSignal | None:
        minimum = max(self.config.slow_ema, self.config.atr_bars + 1, self.config.breakout_bars + 1)
        if len(bars) < minimum:
            return None
        closes = [bar.close for bar in bars[-self.config.slow_ema:]]
        fast = _ema(closes[-self.config.fast_ema:], self.config.fast_ema)
        slow = _ema(closes, self.config.slow_ema)
        current = bars[-1]
        prior_range = bars[-(self.config.breakout_bars + 1):-1]
        prior_high, prior_low = max(bar.high for bar in prior_range), min(bar.low for bar in prior_range)
        atr = _atr(bars, self.config.atr_bars)
        if atr <= 0:
            return None
        features = {
            "fast_ema": round(fast, 6), "slow_ema": round(slow, 6), "atr": round(atr, 6),
            "breakout_bars": self.config.breakout_bars,
            **describe_price_action(
                bars, atr=atr, fast_ema=fast, slow_ema=slow,
            ).features(),
        }
        if fast > slow and current.close > prior_high:
            stop = min(current.low, current.close - self.config.stop_atr_multiple * atr)
            risk = current.close - stop
            if risk > 0:
                return StructureSignal(Side.LONG, current.timestamp, current.close, stop,
                                       current.close + self.config.reward_risk * risk,
                                       {**features, "prior_high": round(prior_high, 6)})
        if fast < slow and current.close < prior_low:
            stop = max(current.high, current.close + self.config.stop_atr_multiple * atr)
            risk = stop - current.close
            if risk > 0:
                return StructureSignal(Side.SHORT, current.timestamp, current.close, stop,
                                       current.close - self.config.reward_risk * risk,
                                       {**features, "prior_low": round(prior_low, 6)})
        return None


OPENING_END = time(9, 45)


@dataclass(frozen=True)
class OpeningRangeBreakoutContext:
    side: Side
    range_high: float
    range_low: float
    breakout_time: datetime
    breakout_close: float

    @property
    def retouch_level(self) -> float:
        return self.range_high if self.side is Side.LONG else self.range_low


def _opening_range(bars: Sequence[Bar]) -> tuple[float, float] | None:
    if not bars:
        return None
    day = bars[-1].timestamp.date()
    session = [bar for bar in bars if bar.timestamp.date() == day]
    anchor = session[-1].timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    expected = [anchor + timedelta(minutes=index) for index in range(15)]
    opening = [bar for bar in session if time(9, 30) <= bar.timestamp.time() < OPENING_END]
    if [bar.timestamp for bar in opening] != expected:
        return None
    return max(bar.high for bar in opening), min(bar.low for bar in opening)


def first_close_confirmed_breakout(
    bars: Sequence[Bar], *, entry_deadline: time = time(11, 0),
) -> OpeningRangeBreakoutContext | None:
    opening = _opening_range(bars)
    if opening is None:
        return None
    high, low = opening
    day = bars[-1].timestamp.date()
    for bar in bars:
        if bar.timestamp.date() != day or not (OPENING_END <= bar.timestamp.time() <= entry_deadline):
            continue
        if bar.close > high:
            return OpeningRangeBreakoutContext(Side.LONG, high, low, bar.timestamp, bar.close)
        if bar.close < low:
            return OpeningRangeBreakoutContext(Side.SHORT, high, low, bar.timestamp, bar.close)
    return None


def retouch_status(
    context: OpeningRangeBreakoutContext, price: float, *, tolerance_pct: float = 0.0005,
) -> str:
    """Return ``ready``, ``touch``, or ``failed`` for the first retest."""
    if price <= 0 or not 0.0 <= tolerance_pct < 0.01:
        raise ValueError("price must be positive and tolerance_pct must be in [0, 0.01)")
    level = context.retouch_level
    tolerance = max(level * tolerance_pct, 0.01)
    if context.side is Side.LONG:
        if price < level - tolerance:
            return "failed"
        if price <= level + tolerance:
            return "touch"
    else:
        if price > level + tolerance:
            return "failed"
        if price >= level - tolerance:
            return "touch"
    return "ready"
