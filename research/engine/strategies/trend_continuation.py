"""A minimal, inspectable Trend Continuation research hypothesis.

This is not a port of the legacy strategy.  It has one visible premise:
when a fast trend is above a slow trend (or below it), a close through the
recent range may continue.  The setup defines its invalidation with ATR and
is filled only on the next bar by :class:`research.engine.simulator.Simulator`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from research.engine.models import Bar, Side, Signal


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

    def __post_init__(self) -> None:
        if not (1 < self.fast_ema < self.slow_ema):
            raise ValueError("fast_ema must be >1 and smaller than slow_ema")
        if self.breakout_bars < 2 or self.atr_bars < 2:
            raise ValueError("breakout_bars and atr_bars must be at least 2")
        if self.stop_atr_multiple <= 0 or self.reward_risk <= 1:
            raise ValueError("stop_atr_multiple must be positive and reward_risk > 1")


class TrendContinuation:
    """Raw directional setup with no confidence score and no external I/O."""

    strategy_id = "V2_TREND_CONT"

    def __init__(self, config: TrendContinuationConfig = TrendContinuationConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        minimum = max(self.config.slow_ema, self.config.atr_bars + 1, self.config.breakout_bars + 1)
        if len(bars) < minimum:
            return None
        closes = [bar.close for bar in bars[-self.config.slow_ema:]]
        fast = _ema(closes[-self.config.fast_ema:], self.config.fast_ema)
        slow = _ema(closes, self.config.slow_ema)
        current = bars[-1]
        prior_range = bars[-(self.config.breakout_bars + 1):-1]
        prior_high = max(bar.high for bar in prior_range)
        prior_low = min(bar.low for bar in prior_range)
        atr = _atr(bars, self.config.atr_bars)
        if atr <= 0:
            return None

        if fast > slow and current.close > prior_high:
            stop = min(current.low, current.close - self.config.stop_atr_multiple * atr)
            risk = current.close - stop
            if risk <= 0:
                return None
            return Signal(
                self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                current.close + self.config.reward_risk * risk,
                {"fast_ema": round(fast, 6), "slow_ema": round(slow, 6),
                 "atr": round(atr, 6), "prior_high": round(prior_high, 6),
                 "breakout_bars": self.config.breakout_bars},
            )
        if fast < slow and current.close < prior_low:
            stop = max(current.high, current.close + self.config.stop_atr_multiple * atr)
            risk = stop - current.close
            if risk <= 0:
                return None
            return Signal(
                self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                current.close - self.config.reward_risk * risk,
                {"fast_ema": round(fast, 6), "slow_ema": round(slow, 6),
                 "atr": round(atr, 6), "prior_low": round(prior_low, 6),
                 "breakout_bars": self.config.breakout_bars},
            )
        return None
