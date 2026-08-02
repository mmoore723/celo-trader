"""Faithful, order-free port of TradingView's open-source SuperTrend strategy.

Source: https://www.tradingview.com/script/P5Gu6F8k/ (KivancOzbilgic,
Pine v4, accessed 2026-08-02).  The original opens or reverses on each trend
flip; it does *not* define a stop, target, or options contract.  Those orders
are reproduced by :mod:`research_v2.supertrend_simulator`, not the generic
stop/target simulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from research_v2.models import Bar, Side, Signal


@dataclass(frozen=True)
class SuperTrendReversalConfig:
    atr_period: int = 10
    multiplier: float = 3.0
    use_rma_atr: bool = True

    def __post_init__(self) -> None:
        if self.atr_period < 2 or self.multiplier <= 0:
            raise ValueError("atr_period must be >= 2 and multiplier positive")


def _true_ranges(bars: Sequence[Bar]) -> list[float]:
    ranges: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            ranges.append(bar.high - bar.low)
        else:
            prior = bars[index - 1]
            ranges.append(max(bar.high - bar.low, abs(bar.high - prior.close), abs(bar.low - prior.close)))
    return ranges


def _atr(values: Sequence[float], period: int, use_rma: bool) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    value = sum(values[:period]) / period
    result[period - 1] = value
    for index in range(period, len(values)):
        value = ((value * (period - 1)) + values[index]) / period if use_rma else sum(values[index - period + 1:index + 1]) / period
        result[index] = value
    return result


class SuperTrendReversal:
    """Emit only a completed-bar SuperTrend trend-flip signal."""

    strategy_id = "TV_SUPERTREND_REVERSAL_V4"

    def __init__(self, config: SuperTrendReversalConfig = SuperTrendReversalConfig()) -> None:
        self.config = config
        self._reset()

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        # The simulator supplies one increasingly long history.  Preserve
        # state for that normal path; rebuild only when a caller supplies a
        # different history (as the unit tests and ad-hoc inspections do).
        if len(bars) == self._seen + 1 and (self._seen == 0 or bars[-2].timestamp == self._last_timestamp):
            return self._advance(bars[-1])
        self._reset()
        signal = None
        for bar in bars:
            signal = self._advance(bar)
        return signal

    def _reset(self) -> None:
        self._seen = 0
        self._last_timestamp = None
        self._last_close: float | None = None
        self._tr_values: list[float] = []
        self._atr_value: float | None = None
        self._up: float | None = None
        self._down: float | None = None
        self._trend = 1

    def _advance(self, current: Bar) -> Signal | None:
        tr = current.high - current.low if self._last_close is None else max(
            current.high - current.low, abs(current.high - self._last_close), abs(current.low - self._last_close)
        )
        self._tr_values.append(tr)
        period = self.config.atr_period
        if len(self._tr_values) < period:
            self._last_close, self._last_timestamp, self._seen = current.close, current.timestamp, self._seen + 1
            return None
        if len(self._tr_values) == period:
            self._atr_value = sum(self._tr_values) / period
        elif self.config.use_rma_atr:
            assert self._atr_value is not None
            self._atr_value = ((self._atr_value * (period - 1)) + tr) / period
        else:
            self._tr_values.pop(0)
            self._atr_value = sum(self._tr_values) / period
        assert self._atr_value is not None
        source = (current.high + current.low) / 2.0
        up = source - self.config.multiplier * self._atr_value
        down = source + self.config.multiplier * self._atr_value
        prior_up = up if self._up is None else self._up
        prior_down = down if self._down is None else self._down
        prior_close = current.close if self._last_close is None else self._last_close
        if prior_close > prior_up:
            up = max(up, prior_up)
        if prior_close < prior_down:
            down = min(down, prior_down)
        prior_trend = self._trend
        trend = 1 if prior_trend == -1 and current.close > prior_down else (-1 if prior_trend == 1 and current.close < prior_up else prior_trend)
        self._up, self._down, self._trend = up, down, trend
        self._last_close, self._last_timestamp, self._seen = current.close, current.timestamp, self._seen + 1
        if trend == prior_trend:
            return None
        side = Side.LONG if trend == 1 else Side.SHORT
        # The generic Signal contract requires these fields.  They are not
        # execution orders here; the reversal simulator exits on the next
        # opposite flip, exactly as the Pine source does.
        stop = current.close - self._atr_value if side is Side.LONG else current.close + self._atr_value
        target = current.close + self._atr_value if side is Side.LONG else current.close - self._atr_value
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target, {
            "atr_period": self.config.atr_period,
            "multiplier": self.config.multiplier,
            "atr_method": "rma" if self.config.use_rma_atr else "sma",
            "source": "hl2",
        })
