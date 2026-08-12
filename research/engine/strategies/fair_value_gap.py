"""Strict, order-free fair-value-gap retest hypothesis for V2 research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr, _ema
from research.engine.strategies.vwap_pullback import _session, _vwaps


@dataclass(frozen=True)
class FairValueGapConfig:
    fast_ema: int = 8
    slow_ema: int = 20
    atr_bars: int = 14
    scan_bars: int = 30
    min_gap_atr: float = 0.5
    stop_atr_multiple: float = 1.0
    reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if self.fast_ema < 2 or self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema, and fast_ema at least 2")
        if self.atr_bars < 2 or self.scan_bars < 3:
            raise ValueError("atr_bars must be at least 2 and scan_bars at least 3")
        if self.min_gap_atr <= 0 or self.stop_atr_multiple <= 0 or self.reward_risk <= 0:
            raise ValueError("gap, stop, and reward/risk values must be positive")


class FairValueGap:
    """First retest of a three-bar imbalance, confirmed by trend and VWAP."""

    strategy_id = "V2_FAIR_VALUE_GAP"

    def __init__(self, config: FairValueGapConfig = FairValueGapConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        minimum = max(self.config.slow_ema, self.config.atr_bars + 1, 6)
        current = today[-1]
        if len(today) < minimum or current.timestamp.time() < time(9, 45):
            return None
        atr = _atr(today, self.config.atr_bars)
        closes = [bar.close for bar in today[-self.config.slow_ema:]]
        fast = _ema(closes[-self.config.fast_ema:], self.config.fast_ema)
        slow = _ema(closes, self.config.slow_ema)
        vwap = _vwaps(today)[-1]
        # A three-bar formation needs one completed bar after it, and the
        # current bar must be the first retest (not the formation bar itself).
        newest = len(today) - 3
        oldest = max(1, newest - self.config.scan_bars + 1)
        for middle in range(newest, oldest - 1, -1):
            before, after = today[middle - 1], today[middle + 1]
            intervening = today[middle + 2:-1]
            # Upward FVG: the high before the impulse is below the low after it.
            if before.high < after.low:
                lower, upper = before.high, after.low
                if upper - lower < self.config.min_gap_atr * atr or not (fast > slow and current.close > vwap):
                    continue
                # A first retest must overlap the zone now and must not have
                # overlapped it on any completed bar since formation.
                if any(bar.low <= upper and bar.high >= lower for bar in intervening):
                    continue
                midpoint = (lower + upper) / 2.0
                if current.low <= upper and current.high >= lower and current.close > midpoint:
                    stop = min(current.low, current.close - self.config.stop_atr_multiple * atr)
                    risk = current.close - stop
                    if risk > 0:
                        return Signal(self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                                      current.close + self.config.reward_risk * risk,
                                      {"gap_lower": round(lower, 6), "gap_upper": round(upper, 6),
                                       "atr": round(atr, 6), "vwap": round(vwap, 6), "trigger": "upward_gap_retest"})
            # Downward FVG: the low before the impulse is above the high after it.
            elif before.low > after.high:
                lower, upper = after.high, before.low
                if upper - lower < self.config.min_gap_atr * atr or not (fast < slow and current.close < vwap):
                    continue
                if any(bar.low <= upper and bar.high >= lower for bar in intervening):
                    continue
                midpoint = (lower + upper) / 2.0
                if current.low <= upper and current.high >= lower and current.close < midpoint:
                    stop = max(current.high, current.close + self.config.stop_atr_multiple * atr)
                    risk = stop - current.close
                    if risk > 0:
                        return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                                      current.close - self.config.reward_risk * risk,
                                      {"gap_lower": round(lower, 6), "gap_upper": round(upper, 6),
                                       "atr": round(atr, 6), "vwap": round(vwap, 6), "trigger": "downward_gap_retest"})
        return None
