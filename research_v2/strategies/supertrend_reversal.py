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

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        if len(bars) < self.config.atr_period + 1:
            return None
        atrs = _atr(_true_ranges(bars), self.config.atr_period, self.config.use_rma_atr)
        up_previous: float | None = None
        down_previous: float | None = None
        trend_previous = 1
        trend = trend_previous
        current_atr = 0.0
        for index, bar in enumerate(bars):
            atr = atrs[index]
            if atr is None:
                continue
            current_atr = atr
            source = (bar.high + bar.low) / 2.0
            up = source - self.config.multiplier * atr
            down = source + self.config.multiplier * atr
            prior_close = bars[index - 1].close if index else bar.close
            prior_up = up if up_previous is None else up_previous
            prior_down = down if down_previous is None else down_previous
            if prior_close > prior_up:
                up = max(up, prior_up)
            if prior_close < prior_down:
                down = min(down, prior_down)
            trend = 1 if trend_previous == -1 and bar.close > prior_down else (-1 if trend_previous == 1 and bar.close < prior_up else trend_previous)
            up_previous, down_previous = up, down
            if index != len(bars) - 1:
                trend_previous = trend

        if trend == trend_previous or current_atr <= 0:
            return None
        current = bars[-1]
        side = Side.LONG if trend == 1 else Side.SHORT
        # The generic Signal contract requires these fields.  They are not
        # execution orders here; the reversal simulator exits on the next
        # opposite flip, exactly as the Pine source does.
        stop = current.close - current_atr if side is Side.LONG else current.close + current_atr
        target = current.close + current_atr if side is Side.LONG else current.close - current_atr
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target, {
            "atr_period": self.config.atr_period,
            "multiplier": self.config.multiplier,
            "atr_method": "rma" if self.config.use_rma_atr else "sma",
            "source": "hl2",
        })
