"""Regular-session VWAP reversion hypothesis, isolated from live trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research_v2.models import Bar, Side, Signal
from research_v2.strategies.trend_continuation import _atr, _ema
from research_v2.strategies.vwap_pullback import _session, _vwaps


@dataclass(frozen=True)
class VWAPReversionRTHConfig:
    atr_bars: int = 14
    ema_bars: int = 20
    band_atr: float = 2.5
    stop_atr: float = 4.0
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)


class VWAPReversionRTH:
    """One flat-market, two-bar rejection back toward session VWAP per day."""

    strategy_id = "V2_VWAP_REVERSION_RTH"

    def __init__(self, config: VWAPReversionRTHConfig = VWAPReversionRTHConfig()) -> None:
        self.config = config
        self._seen, self._last_timestamp = 0, None
        self._today: list[Bar] = []
        self._emitted_day: date | None = None

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = self._current_session(bars)
        current = today[-1]
        minimum = max(self.config.atr_bars + 1, self.config.ema_bars + 11)
        if (len(today) < minimum or self._emitted_day == current.timestamp.date()
                or not self.config.entry_start <= current.timestamp.time() <= self.config.entry_end):
            return None
        vwaps = _vwaps(today)
        atr = _atr(today, self.config.atr_bars)
        prior_atr = _atr(today[:-1], self.config.atr_bars)
        current_vwap, prior_vwap = vwaps[-1], vwaps[-2]
        lower, upper = current_vwap - atr * self.config.band_atr, current_vwap + atr * self.config.band_atr
        prior_lower, prior_upper = prior_vwap - prior_atr * self.config.band_atr, prior_vwap + prior_atr * self.config.band_atr
        closes = [bar.close for bar in today]
        ema_now = _ema(closes[-self.config.ema_bars:], self.config.ema_bars)
        ema_then = _ema(closes[-(self.config.ema_bars + 10):-10], self.config.ema_bars)
        if abs(ema_now - ema_then) >= atr * 0.4:
            return None
        prior = today[-2]
        if (prior.low < prior_lower or current.low < lower) and current.close > lower:
            stop, target = current_vwap - atr * self.config.stop_atr, current_vwap
            if target - current.close >= (current.close - stop) * 1.5:
                return self._emit(Side.LONG, current, stop, target, {"vwap": round(current_vwap, 6), "atr": round(atr, 6), "trigger": "two_bar_lower_band_rejection"})
        if (prior.high > prior_upper or current.high > upper) and current.close < upper:
            stop, target = current_vwap + atr * self.config.stop_atr, current_vwap
            if current.close - target >= (stop - current.close) * 1.5:
                return self._emit(Side.SHORT, current, stop, target, {"vwap": round(current_vwap, 6), "atr": round(atr, 6), "trigger": "two_bar_upper_band_rejection"})
        return None

    def _current_session(self, bars: Sequence[Bar]) -> Sequence[Bar]:
        current = bars[-1]
        if len(bars) == self._seen + 1 and (self._seen == 0 or bars[-2].timestamp == self._last_timestamp):
            self._today = self._today + [current] if self._today and self._today[-1].timestamp.date() == current.timestamp.date() else [current]
        else:
            self._today = _session(bars)
        self._seen, self._last_timestamp = len(bars), current.timestamp
        return self._today

    def _emit(self, side: Side, current: Bar, stop: float, target: float, features: dict) -> Signal:
        self._emitted_day = current.timestamp.date()
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target, features)
