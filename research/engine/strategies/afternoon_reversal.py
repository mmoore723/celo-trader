"""Independent afternoon reversal hypothesis for the V2 research engine.

The rule is intentionally narrower than legacy AFT_REV: after a material
morning extension, wait for two *confirmed* afternoon swing lows/highs and a
break of the opposing swing.  It has no confidence score, router, live-pivot
fallback, or broker dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr
from research.engine.strategies.vwap_pullback import _session, _vwaps


def _confirmed_swings(bars: Sequence[Bar], lookback: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Return only pivots with `lookback` completed bars on both sides."""
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for index in range(lookback, len(bars) - lookback):
        window = bars[index - lookback:index + lookback + 1]
        if bars[index].high == max(bar.high for bar in window):
            highs.append((index, bars[index].high))
        if bars[index].low == min(bar.low for bar in window):
            lows.append((index, bars[index].low))
    return highs, lows


@dataclass(frozen=True)
class AfternoonReversalConfig:
    pivot_lookback: int = 3
    atr_bars: int = 14
    min_morning_move_pct: float = 0.005
    stop_atr_multiple: float = 1.0
    reward_risk: float = 2.0
    start_time: time = time(13, 0)
    end_time: time = time(15, 0)

    def __post_init__(self) -> None:
        if self.pivot_lookback < 1 or self.atr_bars < 2:
            raise ValueError("pivot_lookback must be positive and atr_bars at least 2")
        if not 0 < self.min_morning_move_pct < 0.10:
            raise ValueError("min_morning_move_pct must be between 0 and 0.10")
        if self.stop_atr_multiple <= 0 or self.reward_risk <= 0:
            raise ValueError("stop_atr_multiple and reward_risk must be positive")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")


class AfternoonReversal:
    """Confirmed afternoon reversal after a material morning extension."""

    strategy_id = "V2_AFTERNOON_REVERSAL"

    def __init__(self, config: AfternoonReversalConfig = AfternoonReversalConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        current = today[-1]
        minimum = max(self.config.atr_bars + 1, 2 * self.config.pivot_lookback + 5)
        if len(today) < minimum or not (self.config.start_time <= current.timestamp.time() < self.config.end_time):
            return None

        highs, lows = _confirmed_swings(today, self.config.pivot_lookback)
        if len(highs) < 2 or len(lows) < 2:
            return None
        vwap = _vwaps(today)[-1]
        atr = _atr(today, self.config.atr_bars)
        opening_price = today[0].open
        session_low = min(bar.low for bar in today)
        session_high = max(bar.high for bar in today)
        last_high, prior_high = highs[-1], highs[-2]
        last_low, prior_low = lows[-1], lows[-2]
        feature_base = {
            "vwap": round(vwap, 6), "atr": round(atr, 6),
            "morning_low": round(session_low, 6), "morning_high": round(session_high, 6),
        }

        # Morning sell-off, then higher low and break above the confirmed swing high.
        morning_selloff = (opening_price - session_low) / opening_price >= self.config.min_morning_move_pct
        if (morning_selloff and last_low[1] > prior_low[1] and current.close > last_high[1]
                and current.close > vwap):
            stop = min(last_low[1], current.close - self.config.stop_atr_multiple * atr)
            risk = current.close - stop
            if risk > 0:
                return Signal(self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                              current.close + self.config.reward_risk * risk,
                              {**feature_base, "trigger": "morning_selloff_higher_low_bos"})

        # Morning rally, then lower high and break below the confirmed swing low.
        morning_rally = (session_high - opening_price) / opening_price >= self.config.min_morning_move_pct
        if (morning_rally and last_high[1] < prior_high[1] and current.close < last_low[1]
                and current.close < vwap):
            stop = max(last_high[1], current.close + self.config.stop_atr_multiple * atr)
            risk = stop - current.close
            if risk > 0:
                return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                              current.close - self.config.reward_risk * risk,
                              {**feature_base, "trigger": "morning_rally_lower_high_bos"})
        return None
