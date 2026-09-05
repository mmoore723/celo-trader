"""Causal first-pullback continuation around an impulse-anchored VWAP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal


@dataclass(frozen=True)
class ImpulseAnchoredVwapConfig:
    channel_bars: int = 12
    atr_period: int = 14
    impulse_range_atr: float = 1.50
    close_location_minimum: float = 0.75
    minimum_pullback_bars: int = 2
    maximum_pullback_bars: int = 12
    touch_tolerance_atr: float = 0.15
    failure_tolerance_atr: float = 0.25
    stop_buffer_atr: float = 0.20
    target_r: float = 2.0
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)


class ImpulseAnchoredVwapPullback:
    strategy_id = "V2_IMPULSE_ANCHORED_VWAP_PULLBACK"

    def __init__(self, config: ImpulseAnchoredVwapConfig = ImpulseAnchoredVwapConfig()) -> None:
        self.config = config
        self._processed = 0
        self._day: date | None = None
        self._today: list[Bar] = []
        self._atr: float | None = None
        self._ema20: float | None = None
        self._previous_close: float | None = None
        self._anchor_index: int | None = None
        self._anchor_side: Side | None = None
        self._cum_pv = 0.0
        self._cum_volume = 0.0
        self._pullback_extreme: float | None = None
        self._touched = False
        self._fired = False

    @staticmethod
    def _ema(previous: float | None, value: float, length: int) -> float:
        return value if previous is None else previous + 2.0 / (length + 1.0) * (value - previous)

    def _reset(self, day: date) -> None:
        self._day = day
        self._today = []
        self._atr = self._ema20 = self._previous_close = None
        self._anchor_index = None
        self._anchor_side = None
        self._cum_pv = self._cum_volume = 0.0
        self._pullback_extreme = None
        self._touched = self._fired = False

    def _start_anchor(self, index: int, side: Side, bar: Bar) -> None:
        self._anchor_index = index
        self._anchor_side = side
        typical = (bar.high + bar.low + bar.close) / 3.0
        volume = max(bar.volume, 1.0)
        self._cum_pv = typical * volume
        self._cum_volume = volume
        self._pullback_extreme = bar.low if side is Side.LONG else bar.high
        self._touched = False

    def _detect_impulse(self, bar: Bar) -> None:
        if self._atr is None or self._ema20 is None or len(self._today) <= self.config.channel_bars:
            return
        prior = self._today[-self.config.channel_bars - 1:-1]
        spread = max(bar.high - bar.low, 1e-9)
        close_location = (bar.close - bar.low) / spread
        expanded = spread >= self.config.impulse_range_atr * self._atr
        index = len(self._today) - 1
        if (
            expanded and bar.close > max(x.high for x in prior)
            and close_location >= self.config.close_location_minimum and bar.close > self._ema20
        ):
            self._start_anchor(index, Side.LONG, bar)
        elif (
            expanded and bar.close < min(x.low for x in prior)
            and close_location <= 1.0 - self.config.close_location_minimum and bar.close < self._ema20
        ):
            self._start_anchor(index, Side.SHORT, bar)

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        if len(bars) != self._processed + 1:
            raise ValueError("ImpulseAnchoredVwapPullback requires sequential completed bars")
        bar = bars[-1]
        self._processed += 1
        if self._day != bar.timestamp.date():
            self._reset(bar.timestamp.date())
        previous_close = self._previous_close
        true_range = bar.high - bar.low if previous_close is None else max(
            bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)
        )
        self._atr = self._ema(self._atr, true_range, self.config.atr_period)
        self._ema20 = self._ema(self._ema20, bar.close, 20)
        self._previous_close = bar.close
        self._today.append(bar)
        if self._fired or self._atr is None or not (
            self.config.entry_start <= bar.timestamp.time() <= self.config.entry_end
        ):
            return None
        if self._anchor_index is None:
            self._detect_impulse(bar)
            return None
        bars_since_anchor = len(self._today) - 1 - self._anchor_index
        if bars_since_anchor > self.config.maximum_pullback_bars:
            self._anchor_index = None
            self._anchor_side = None
            self._detect_impulse(bar)
            return None
        typical = (bar.high + bar.low + bar.close) / 3.0
        volume = max(bar.volume, 1.0)
        self._cum_pv += typical * volume
        self._cum_volume += volume
        anchored_vwap = self._cum_pv / self._cum_volume
        if self._anchor_side is Side.LONG:
            self._pullback_extreme = min(float(self._pullback_extreme), bar.low)
            if bar.close < anchored_vwap - self.config.failure_tolerance_atr * self._atr:
                self._anchor_index = self._anchor_side = None
                return None
            self._touched = self._touched or bar.low <= anchored_vwap + self.config.touch_tolerance_atr * self._atr
            reclaimed = (
                self._touched and bars_since_anchor >= self.config.minimum_pullback_bars
                and bar.close > anchored_vwap and bar.close > bar.open
            )
            if reclaimed:
                stop = float(self._pullback_extreme) - self.config.stop_buffer_atr * self._atr
                risk = bar.close - stop
                if risk > 0:
                    self._fired = True
                    return Signal(
                        self.strategy_id, Side.LONG, bar.timestamp, bar.close, stop,
                        bar.close + self.config.target_r * risk,
                        {"anchor_time": str(self._today[self._anchor_index].timestamp),
                         "anchored_vwap": anchored_vwap, "atr": self._atr},
                    )
        else:
            self._pullback_extreme = max(float(self._pullback_extreme), bar.high)
            if bar.close > anchored_vwap + self.config.failure_tolerance_atr * self._atr:
                self._anchor_index = self._anchor_side = None
                return None
            self._touched = self._touched or bar.high >= anchored_vwap - self.config.touch_tolerance_atr * self._atr
            reclaimed = (
                self._touched and bars_since_anchor >= self.config.minimum_pullback_bars
                and bar.close < anchored_vwap and bar.close < bar.open
            )
            if reclaimed:
                stop = float(self._pullback_extreme) + self.config.stop_buffer_atr * self._atr
                risk = stop - bar.close
                if risk > 0:
                    self._fired = True
                    return Signal(
                        self.strategy_id, Side.SHORT, bar.timestamp, bar.close, stop,
                        bar.close - self.config.target_r * risk,
                        {"anchor_time": str(self._today[self._anchor_index].timestamp),
                         "anchored_vwap": anchored_vwap, "atr": self._atr},
                    )
        return None
