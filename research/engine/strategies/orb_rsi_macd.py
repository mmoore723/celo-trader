"""Opening-range breakout with completed-bar RSI/MACD confirmation.

This is a separate research hypothesis, not a retrofit of the bot's existing
ORB.  Its indicators use the preceding regular-session bar history supplied
by the runner, exactly as a chart indicator would at the time of the signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.opening_range_breakout import OpeningRangeBreakoutConfig
from research.engine.strategies.vwap_pullback import _session


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    for price in values[period:]:
        value += (price - value) * multiplier
    return value


def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    moves = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = sum(max(move, 0.0) for move in moves[:period]) / period
    losses = sum(max(-move, 0.0) for move in moves[:period]) / period
    for move in moves[period:]:
        gains = (gains * (period - 1) + max(move, 0.0)) / period
        losses = (losses * (period - 1) + max(-move, 0.0)) / period
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


@dataclass(frozen=True)
class ORBRsiMacdShortConfig:
    min_range_pct: float = 0.0005
    max_range_pct: float = 0.0035
    entry_deadline: time = time(11, 0)
    rsi_period: int = 14
    rsi_ceiling: float = 45.0
    macd_fast: int = 12
    macd_slow: int = 26
    active_date: date | None = None


class ORBRsiMacdShort:
    """One VWAP-aligned bearish opening-range break with bearish momentum."""

    strategy_id = "V2_SPY_ORB_RSI_MACD_SHORT"

    def __init__(self, config: ORBRsiMacdShortConfig = ORBRsiMacdShortConfig()) -> None:
        self.config = config
        self._emitted_day: date | None = None

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        current = bars[-1]
        today = _session(bars)
        if (self.config.active_date is not None and current.timestamp.date() != self.config.active_date
                or self._emitted_day == current.timestamp.date()
                or not time(9, 45) <= current.timestamp.time() <= self.config.entry_deadline):
            return None
        opening = [bar for bar in today if bar.timestamp.time() in (time(9, 30), time(9, 35), time(9, 40))]
        if len(opening) != 3:
            return None
        high, low = max(bar.high for bar in opening), min(bar.low for bar in opening)
        range_pct = (high - low) / current.close
        if not self.config.min_range_pct <= range_pct <= self.config.max_range_pct:
            return None
        prices = [bar.close for bar in bars]
        rsi = _rsi(prices, self.config.rsi_period)
        fast = _ema(prices, self.config.macd_fast)
        slow = _ema(prices, self.config.macd_slow)
        if rsi is None or fast is None or slow is None:
            return None
        volume = sum(max(bar.volume, 1.0) for bar in today)
        vwap = sum((bar.high + bar.low + bar.close) / 3 * max(bar.volume, 1.0) for bar in today) / volume
        buffer = current.close * 0.0002
        if not (current.close < low - buffer and current.close < vwap
                and rsi < self.config.rsi_ceiling and fast < slow):
            return None
        stop = low + (high - low) * 0.5
        risk = stop - current.close
        if risk <= 0:
            return None
        self._emitted_day = current.timestamp.date()
        return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                      current.close - risk * 1.5, {
                          "or_high": round(high, 6), "or_low": round(low, 6),
                          "or_range_pct": round(range_pct, 6), "vwap": round(vwap, 6),
                          "rsi_14": round(rsi, 4), "macd_line": round(fast - slow, 6),
                          "trigger": "narrow_orb_short_rsi_below_45_macd_below_zero",
                      })
