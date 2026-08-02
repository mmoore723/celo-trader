"""Strict opening-range breakout pullback hypothesis for V2 research.

This deliberately differs from the legacy INST_ORB implementation: it has no
immediate-entry path, confidence score, dynamic threshold, persistent state,
or live pivot fallback.  Each evaluation derives one causal setup from closed
five-minute bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research_v2.models import Bar, Side, Signal
from research_v2.strategies.trend_continuation import _atr
from research_v2.strategies.vwap_pullback import _session, _vwaps


@dataclass(frozen=True)
class OpeningRangePullbackConfig:
    atr_bars: int = 14
    retest_tolerance_pct: float = 0.001
    breakout_deadline: time = time(10, 30)
    entry_deadline: time = time(10, 45)
    reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if self.atr_bars < 2:
            raise ValueError("atr_bars must be at least 2")
        if not 0 < self.retest_tolerance_pct < 0.01:
            raise ValueError("retest_tolerance_pct must be between 0 and 0.01")
        if self.entry_deadline <= self.breakout_deadline or self.reward_risk <= 0:
            raise ValueError("entry deadline must follow breakout deadline and reward/risk be positive")


def _opening_range(today: Sequence[Bar]) -> tuple[float, float] | None:
    slots = (time(9, 30), time(9, 35), time(9, 40))
    opening = [bar for bar in today if bar.timestamp.time() in slots]
    if len(opening) != 3:
        return None
    return max(bar.high for bar in opening), min(bar.low for bar in opening)


class OpeningRangePullback:
    """First post-breakout retest and bounce of the completed 15-minute range."""

    strategy_id = "V2_ORB_PULLBACK"

    def __init__(self, config: OpeningRangePullbackConfig = OpeningRangePullbackConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        current = today[-1]
        opening = _opening_range(today)
        if opening is None or len(today) < self.config.atr_bars + 1:
            return None
        if not (time(9, 50) <= current.timestamp.time() <= self.config.entry_deadline):
            return None
        or_high, or_low = opening
        vwap = _vwaps(today)[-1]
        atr = _atr(today, self.config.atr_bars)
        tolerance = max(or_high * self.config.retest_tolerance_pct, 0.01)
        # Current bar cannot be part of breakout/retest discovery.  This makes
        # the bounce confirmation explicit and prevents same-bar hindsight.
        prior = today[:-1]
        eligible = [index for index, bar in enumerate(prior)
                    if time(9, 45) <= bar.timestamp.time() <= self.config.breakout_deadline]
        for index in eligible:
            breakout = prior[index]
            if breakout.close > or_high:
                retests = [bar for bar in prior[index + 1:]
                           if bar.low <= or_high + tolerance]
                if not retests:
                    continue
                retest = retests[0]
                if any(bar.close < or_low for bar in prior[index + 1:]):
                    continue
                if current.close > or_high and current.close > today[-2].high and current.close > vwap:
                    stop = retest.low
                    risk = current.close - stop
                    if risk > 0:
                        return Signal(self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                                      current.close + self.config.reward_risk * risk,
                                      {"or_high": round(or_high, 6), "or_low": round(or_low, 6),
                                       "atr": round(atr, 6), "vwap": round(vwap, 6),
                                       "trigger": "upward_breakout_first_retest_bounce"})
            elif breakout.close < or_low:
                retests = [bar for bar in prior[index + 1:]
                           if bar.high >= or_low - tolerance]
                if not retests:
                    continue
                retest = retests[0]
                if any(bar.close > or_high for bar in prior[index + 1:]):
                    continue
                if current.close < or_low and current.close < today[-2].low and current.close < vwap:
                    stop = retest.high
                    risk = stop - current.close
                    if risk > 0:
                        return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                                      current.close - self.config.reward_risk * risk,
                                      {"or_high": round(or_high, 6), "or_low": round(or_low, 6),
                                       "atr": round(atr, 6), "vwap": round(vwap, 6),
                                       "trigger": "downward_breakout_first_retest_bounce"})
        return None
