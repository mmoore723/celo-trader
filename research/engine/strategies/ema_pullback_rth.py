"""RTH adaptation of TradingView's open-source EMA pullback strategy.

The published strategy was written for 15-minute crypto data.  This research
candidate preserves its three-EMA pullback/recross and 2.06R exit rules, but
only emits regular-session signals.  The shared simulator then flattens any
open position at 15:55 ET; this avoids pretending an intraday options idea can
quietly carry risk overnight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research.engine.models import Bar, Side, Signal


@dataclass(frozen=True)
class EMAPullbackRTHConfig:
    """Source defaults, except for an explicit regular-hours entry window."""

    pullback_ema: int = 33
    pullback_limit_ema: int = 165
    trend_ema: int = 365
    minimum_risk_pct: float = 0.008
    target_risk_ratio: float = 2.06
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)

    def __post_init__(self) -> None:
        if not (1 < self.pullback_ema < self.pullback_limit_ema < self.trend_ema):
            raise ValueError("EMA lengths must be ordered pullback < limit < trend")
        if not 0 < self.minimum_risk_pct < 0.25:
            raise ValueError("minimum_risk_pct must be in (0, .25)")
        if self.target_risk_ratio <= 1:
            raise ValueError("target_risk_ratio must be greater than one")
        if self.entry_start >= self.entry_end:
            raise ValueError("entry_start must be before entry_end")


class EMAPullbackRTH:
    """Incremental, source-auditable EMA pullback/re-cross hypothesis."""

    strategy_id = "V2_EMA_PULLBACK_RTH"

    def __init__(self, config: EMAPullbackRTHConfig = EMAPullbackRTHConfig()) -> None:
        self.config = config
        self._processed = 0
        self._fast: float | None = None
        self._limit: float | None = None
        self._trend: float | None = None
        self._previous_close: float | None = None
        self._previous_fast: float | None = None
        self._above_max_close: float | None = None
        self._above_max_high: float | None = None
        self._below_min_close: float | None = None
        self._below_min_low: float | None = None

    @staticmethod
    def _next_ema(previous: float | None, close: float, length: int) -> float:
        if previous is None:
            return close
        alpha = 2.0 / (length + 1.0)
        return alpha * close + (1.0 - alpha) * previous

    def _advance(self, bar: Bar) -> tuple[bool, bool]:
        """Consume one completed bar and return its up/down EMA crossings."""
        fast_before = self._fast
        prior_close = self._previous_close
        self._fast = self._next_ema(self._fast, bar.close, self.config.pullback_ema)
        self._limit = self._next_ema(self._limit, bar.close, self.config.pullback_limit_ema)
        self._trend = self._next_ema(self._trend, bar.close, self.config.trend_ema)
        crossed_up = prior_close is not None and fast_before is not None and prior_close <= fast_before and bar.close > self._fast
        crossed_down = prior_close is not None and fast_before is not None and prior_close >= fast_before and bar.close < self._fast

        if crossed_up:
            self._above_max_close, self._above_max_high = bar.close, bar.high
        elif self._above_max_close is not None:
            self._above_max_close = max(self._above_max_close, bar.close)
            self._above_max_high = max(self._above_max_high or bar.high, bar.high)

        if crossed_down:
            self._below_min_close, self._below_min_low = bar.close, bar.low
        elif self._below_min_close is not None:
            self._below_min_close = min(self._below_min_close, bar.close)
            self._below_min_low = min(self._below_min_low or bar.low, bar.low)

        self._previous_close, self._previous_fast = bar.close, self._fast
        self._processed += 1
        return crossed_up, crossed_down

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        # Simulator supplies exactly one appended bar for each evaluation.
        # Reject non-sequential use instead of silently creating different EMA
        # state from a partial history.
        if len(bars) != self._processed + 1:
            raise ValueError("EMAPullbackRTH requires sequential completed bars")
        current = bars[-1]
        crossed_up, crossed_down = self._advance(current)
        if self._processed < self.config.trend_ema or not (self.config.entry_start <= current.timestamp.time() <= self.config.entry_end):
            return None
        assert self._fast is not None and self._limit is not None and self._trend is not None

        if crossed_up and self._below_min_close is not None and self._below_min_low is not None and self._below_min_close < self._limit and self._fast > self._trend:
            risk = (current.close - self._below_min_low) / current.close
            if self.config.minimum_risk_pct < risk < 1:
                return Signal(self.strategy_id, Side.LONG, current.timestamp, current.close,
                              self._below_min_low, current.close * (1 + self.config.target_risk_ratio * risk),
                              {"ema_fast": round(self._fast, 6), "ema_limit": round(self._limit, 6),
                               "ema_trend": round(self._trend, 6), "risk_pct": round(risk * 100, 4),
                               "source": "TradingView Space_Jellyfish EMA pullback (RTH adaptation)"})
        if crossed_down and self._above_max_close is not None and self._above_max_high is not None and self._above_max_close > self._limit and self._fast < self._trend:
            risk = (self._above_max_high - current.close) / current.close
            if self.config.minimum_risk_pct < risk < 1:
                return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close,
                              self._above_max_high, current.close * (1 - self.config.target_risk_ratio * risk),
                              {"ema_fast": round(self._fast, 6), "ema_limit": round(self._limit, 6),
                               "ema_trend": round(self._trend, 6), "risk_pct": round(risk * 100, 4),
                               "source": "TradingView Space_Jellyfish EMA pullback (RTH adaptation)"})
        return None
