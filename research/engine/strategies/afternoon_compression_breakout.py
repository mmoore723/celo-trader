"""Afternoon compression-to-expansion hypothesis for paid-data research.

From 12:30 through 13:14 Eastern, price forms a compact lunchtime box.
Beginning at 13:15, a completed one-minute candle must close outside that box
while price, VWAP, and EMA(9/20) agree on direction. A research simulator may
fill only on the following minute. The rule emits at most once per session and
has no broker, account, or order dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr, _ema
from research.engine.strategies.vwap_pullback import _session, _vwaps


@dataclass(frozen=True)
class AfternoonCompressionBreakoutConfig:
    fast_ema: int = 9
    slow_ema: int = 20
    atr_bars: int = 14
    compression_start: time = time(12, 30)
    compression_end: time = time(13, 15)
    entry_end: time = time(14, 30)
    min_compression_bars: int = 30
    max_compression_pct: float = 0.0025
    stop_atr_multiple: float = 1.0
    reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if not (1 < self.fast_ema < self.slow_ema):
            raise ValueError("EMAs must be positive and fast must precede slow")
        if self.atr_bars < 2 or self.min_compression_bars < 2:
            raise ValueError("ATR and compression lengths must be usable")
        if not (self.compression_start < self.compression_end < self.entry_end):
            raise ValueError("compression and entry times must be ordered")
        if not 0 < self.max_compression_pct < .05:
            raise ValueError("compression percentage must be between zero and five percent")
        if self.stop_atr_multiple <= 0 or self.reward_risk <= 0:
            raise ValueError("risk measurements must be positive")


class AfternoonCompressionBreakout:
    """One VWAP-aligned break from a compact afternoon range per session."""

    strategy_id = "V2_AFTERNOON_COMPRESSION_BREAKOUT"

    def __init__(
        self,
        config: AfternoonCompressionBreakoutConfig = AfternoonCompressionBreakoutConfig(),
    ) -> None:
        self.config = config
        self._seen = 0
        self._last_timestamp = None
        self._today: list[Bar] = []
        self._compression: list[Bar] = []
        self._range: tuple[float, float] | None = None
        self._rejected_day: date | None = None
        self._emitted_day: date | None = None

    def _current_session(self, bars: Sequence[Bar]) -> list[Bar]:
        current = bars[-1]
        sequential = len(bars) == self._seen + 1 and (
            self._seen == 0 or bars[-2].timestamp == self._last_timestamp
        )
        if sequential:
            if self._today and self._today[-1].timestamp.date() == current.timestamp.date():
                self._today.append(current)
            else:
                self._today = [current]
                self._compression, self._range = [], None
                self._rejected_day = None
        else:
            self._today = list(_session(bars))
            self._compression, self._range = [], None
            self._rejected_day = None
        self._seen, self._last_timestamp = len(bars), current.timestamp
        return self._today

    def _freeze_range(self, current: Bar) -> None:
        if self._range is not None or self._rejected_day == current.timestamp.date():
            return
        if len(self._compression) < self.config.min_compression_bars:
            self._rejected_day = current.timestamp.date()
            return
        high = max(bar.high for bar in self._compression)
        low = min(bar.low for bar in self._compression)
        midpoint = (high + low) / 2.0
        if midpoint <= 0 or (high - low) / midpoint > self.config.max_compression_pct:
            self._rejected_day = current.timestamp.date()
            return
        self._range = (high, low)

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = self._current_session(bars)
        current = today[-1]
        now = current.timestamp.time()
        if self._emitted_day == current.timestamp.date():
            return None
        if self.config.compression_start <= now < self.config.compression_end:
            self._compression.append(current)
            return None
        if now < self.config.compression_end or now > self.config.entry_end:
            return None
        self._freeze_range(current)
        if self._range is None:
            return None
        minimum = max(self.config.slow_ema, self.config.atr_bars + 1)
        if len(today) < minimum:
            return None
        atr = _atr(today, self.config.atr_bars)
        if atr <= 0:
            return None
        closes = [bar.close for bar in today[-self.config.slow_ema:]]
        fast = _ema(closes[-self.config.fast_ema:], self.config.fast_ema)
        slow = _ema(closes, self.config.slow_ema)
        vwap = _vwaps(today)[-1]
        range_high, range_low = self._range
        range_pct = (range_high - range_low) / ((range_high + range_low) / 2.0) * 100
        features = {
            "compression_high": round(range_high, 6),
            "compression_low": round(range_low, 6),
            "compression_pct": round(range_pct, 4),
            "vwap": round(vwap, 6),
            "fast_ema": round(fast, 6),
            "slow_ema": round(slow, 6),
            "atr": round(atr, 6),
        }
        if current.close > range_high and current.close > vwap and fast > slow:
            stop = min(range_low, current.close - self.config.stop_atr_multiple * atr)
            risk = current.close - stop
            if risk > 0:
                self._emitted_day = current.timestamp.date()
                return Signal(
                    self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                    current.close + self.config.reward_risk * risk,
                    {**features, "trigger": "afternoon_compact_range_upward_expansion"},
                )
        if current.close < range_low and current.close < vwap and fast < slow:
            stop = max(range_high, current.close + self.config.stop_atr_multiple * atr)
            risk = stop - current.close
            if risk > 0:
                self._emitted_day = current.timestamp.date()
                return Signal(
                    self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                    current.close - self.config.reward_risk * risk,
                    {**features, "trigger": "afternoon_compact_range_downward_expansion"},
                )
        return None
