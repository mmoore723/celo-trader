"""Later-morning consolidation breakdown hypothesis for V2 research.

This is a clean replacement *hypothesis* for legacy ``MID_BRK``.  It does
not reuse the first 15-minute opening range, confidence score, or router
state.  The only premise being tested is deliberately simple: after TSLA has
formed a compact base between 10:00 and 11:00, a confirmed close below that
base and VWAP may continue lower.

Signals use completed five-minute bars and are filled by the simulator on the
next bar.  The class has no broker or live-bot dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr
from research.engine.strategies.vwap_pullback import _session, _vwaps


@dataclass(frozen=True)
class MiddayBreakdownConfig:
    """Fixed, causal rules selected before looking at this V2 result."""

    base_start: time = time(10, 0)
    base_end: time = time(11, 0)
    entry_start: time = time(11, 5)
    entry_end: time = time(13, 30)
    atr_bars: int = 14
    max_base_atr_multiple: float = 3.0
    stop_atr_multiple: float = 0.75
    reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if not (self.base_start < self.base_end < self.entry_start <= self.entry_end):
            raise ValueError("base and entry windows must be chronological")
        if self.atr_bars < 2 or self.max_base_atr_multiple <= 0:
            raise ValueError("atr_bars and max_base_atr_multiple must be positive")
        if self.stop_atr_multiple <= 0 or self.reward_risk <= 1:
            raise ValueError("stop_atr_multiple must be positive and reward_risk > 1")


class MiddayBreakdown:
    """One later-morning base breakdown per regular session."""

    strategy_id = "V2_MIDDAY_BREAKDOWN"

    def __init__(self, config: MiddayBreakdownConfig = MiddayBreakdownConfig()) -> None:
        self.config = config
        self._emitted_day: date | None = None

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        current = today[-1]
        if self._emitted_day == current.timestamp.date():
            return None
        if not (self.config.entry_start <= current.timestamp.time() <= self.config.entry_end):
            return None
        base = [bar for bar in today if self.config.base_start <= bar.timestamp.time() <= self.config.base_end]
        if len(base) < 13 or len(today) < self.config.atr_bars + 1:
            return None
        # The current completed candle is a confirmation candle.  It cannot
        # help create the base it is breaking, which prevents look-ahead.
        base_high = max(bar.high for bar in base)
        base_low = min(bar.low for bar in base)
        atr = _atr(today, self.config.atr_bars)
        if atr <= 0 or (base_high - base_low) > self.config.max_base_atr_multiple * atr:
            return None
        vwap = _vwaps(today)[-1]
        prior = today[-2]
        if not (current.close < base_low and current.close < vwap and prior.close >= base_low):
            return None
        stop = max(base_high, current.close + self.config.stop_atr_multiple * atr)
        risk = stop - current.close
        if risk <= 0:
            return None
        self._emitted_day = current.timestamp.date()
        return Signal(
            self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
            current.close - self.config.reward_risk * risk,
            {
                "base_high": round(base_high, 6), "base_low": round(base_low, 6),
                "base_range_atr": round((base_high - base_low) / atr, 6),
                "atr": round(atr, 6), "vwap": round(vwap, 6),
                "trigger": "later_morning_base_breakdown_below_vwap",
            },
        )
