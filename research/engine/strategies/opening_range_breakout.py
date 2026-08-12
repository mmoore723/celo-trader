"""A simple, auditable US-session opening-range breakout research candidate.

This is intentionally not a patch to the rejected pullback strategy.  It asks
a different question: after the first 15 minutes, does one confirmed move out
of a suitably sized opening range continue far enough to justify a defined
risk?  It is research-only and has no broker or database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.vwap_pullback import _session


@dataclass(frozen=True)
class OpeningRangeBreakoutConfig:
    min_range_pct: float = 0.002
    max_range_pct: float = 0.012
    breakout_buffer_pct: float = 0.0002
    entry_deadline: time = time(11, 0)
    stop_range_fraction: float = 0.5
    reward_risk: float = 1.5
    allow_long: bool = True
    allow_short: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.min_range_pct < self.max_range_pct < 0.1:
            raise ValueError("opening-range limits must be ordered fractions")
        if not 0 <= self.breakout_buffer_pct < 0.01:
            raise ValueError("breakout buffer must be a small non-negative fraction")
        if not 0 < self.stop_range_fraction <= 1 or self.reward_risk <= 0:
            raise ValueError("stop fraction and reward/risk must be positive")
        if not self.allow_long and not self.allow_short:
            raise ValueError("at least one breakout direction must be enabled")


class OpeningRangeBreakout:
    """One close-confirmed, VWAP-aligned breakout per regular session."""

    strategy_id = "V2_ORB_CONFIRMED_BREAKOUT"

    def __init__(self, config: OpeningRangeBreakoutConfig = OpeningRangeBreakoutConfig()) -> None:
        self.config = config
        self._seen = 0
        self._last_timestamp = None
        self._today: list[Bar] = []
        self._emitted_day: date | None = None
        self._session_price_volume = 0.0
        self._session_volume = 0.0

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = self._current_session(bars)
        current = today[-1]
        if self._emitted_day == current.timestamp.date() or not (time(9, 45) <= current.timestamp.time() <= self.config.entry_deadline):
            return None
        opening = [bar for bar in today if bar.timestamp.time() in (time(9, 30), time(9, 35), time(9, 40))]
        if len(opening) != 3:
            return None
        high, low = max(bar.high for bar in opening), min(bar.low for bar in opening)
        range_pct = (high - low) / current.close
        if not self.config.min_range_pct <= range_pct <= self.config.max_range_pct:
            return None
        # Most callers add one completed bar at a time.  Keep the exact same
        # typical-price VWAP incrementally rather than recomputing every bar
        # of the session for every tuning candidate.  The fallback path in
        # _current_session recalculates this state for non-sequential callers.
        vwap = self._session_price_volume / self._session_volume
        buffer = current.close * self.config.breakout_buffer_pct
        if self.config.allow_long and current.close > high + buffer and current.close > vwap:
            stop = high - (high - low) * self.config.stop_range_fraction
            risk = current.close - stop
            if risk > 0:
                return self._emit(Side.LONG, current, stop, current.close + risk * self.config.reward_risk,
                                  {"or_high": round(high, 6), "or_low": round(low, 6),
                                   "or_range_pct": round(range_pct, 6), "vwap": round(vwap, 6),
                                   "trigger": "close_confirmed_vwap_aligned_long"})
        if self.config.allow_short and current.close < low - buffer and current.close < vwap:
            stop = low + (high - low) * self.config.stop_range_fraction
            risk = stop - current.close
            if risk > 0:
                return self._emit(Side.SHORT, current, stop, current.close - risk * self.config.reward_risk,
                                  {"or_high": round(high, 6), "or_low": round(low, 6),
                                   "or_range_pct": round(range_pct, 6), "vwap": round(vwap, 6),
                                   "trigger": "close_confirmed_vwap_aligned_short"})
        return None

    def _current_session(self, bars: Sequence[Bar]) -> Sequence[Bar]:
        current = bars[-1]
        if len(bars) == self._seen + 1 and (self._seen == 0 or bars[-2].timestamp == self._last_timestamp):
            if not self._today or self._today[-1].timestamp.date() == current.timestamp.date():
                self._today.append(current)
            else:
                self._today = [current]
                self._session_price_volume = self._session_volume = 0.0
            self._add_to_vwap(current)
            self._seen, self._last_timestamp = len(bars), current.timestamp
            return self._today
        self._today = _session(bars)
        self._session_price_volume = self._session_volume = 0.0
        for bar in self._today:
            self._add_to_vwap(bar)
        self._seen, self._last_timestamp = len(bars), current.timestamp
        return self._today

    def _add_to_vwap(self, bar: Bar) -> None:
        volume = max(bar.volume, 1.0)
        self._session_price_volume += (bar.high + bar.low + bar.close) / 3.0 * volume
        self._session_volume += volume

    def _emit(self, side: Side, current: Bar, stop: float, target: float, features: dict) -> Signal:
        self._emitted_day = current.timestamp.date()
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target, features)
