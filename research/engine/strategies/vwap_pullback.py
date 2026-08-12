"""A clean VWAP pullback hypothesis with no router or confidence coupling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr, _ema


def _session(bars: Sequence[Bar]) -> list[Bar]:
    """Return only the current regular-session bars.

    Callers provide chronological history.  Walking backwards until the prior
    date is reached is exactly equivalent to filtering the whole history, but
    keeps long multi-year screens proportional to a single trading day rather
    than every bar seen since the dataset began.
    """
    current_date = bars[-1].timestamp.date()
    start = len(bars) - 1
    while start and bars[start - 1].timestamp.date() == current_date:
        start -= 1
    return list(bars[start:])


def _vwaps(bars: Sequence[Bar]) -> list[float]:
    cumulative_price_volume = cumulative_volume = 0.0
    values: list[float] = []
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        volume = max(bar.volume, 1.0)
        cumulative_price_volume += typical * volume
        cumulative_volume += volume
        values.append(cumulative_price_volume / cumulative_volume)
    return values


@dataclass(frozen=True)
class VWAPPullbackConfig:
    fast_ema: int = 8
    slow_ema: int = 20
    atr_bars: int = 14
    slope_bars: int = 5
    touch_tolerance_pct: float = 0.0015
    stop_atr_multiple: float = 1.0
    reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if self.fast_ema < 2 or self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema, and fast_ema must be at least 2")
        if self.atr_bars < 2 or self.slope_bars < 1:
            raise ValueError("atr_bars must be at least 2 and slope_bars at least 1")
        if not 0 < self.touch_tolerance_pct < 0.02:
            raise ValueError("touch_tolerance_pct must be between 0 and 0.02")
        if self.stop_atr_multiple <= 0 or self.reward_risk <= 0:
            raise ValueError("stop_atr_multiple and reward_risk must be positive")


class VWAPPullback:
    """Session VWAP touch-and-reclaim/rejection setup, research-only."""

    strategy_id = "V2_VWAP_PULLBACK"

    def __init__(self, config: VWAPPullbackConfig = VWAPPullbackConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        minimum = max(self.config.slow_ema, self.config.atr_bars + 1, self.config.slope_bars + 2)
        if len(today) < minimum or today[-1].timestamp.time() < time(9, 45):
            return None
        vwaps = _vwaps(today)
        current, prior = today[-1], today[-2]
        current_vwap, prior_vwap = vwaps[-1], vwaps[-2]
        closes = [bar.close for bar in today[-self.config.slow_ema:]]
        fast = _ema(closes[-self.config.fast_ema:], self.config.fast_ema)
        slow = _ema(closes, self.config.slow_ema)
        atr = _atr(today, self.config.atr_bars)
        tolerance = prior_vwap * self.config.touch_tolerance_pct
        recent_above = sum(bar.close > vwap for bar, vwap in zip(today[-7:-2], vwaps[-7:-2])) >= 4
        recent_below = sum(bar.close < vwap for bar, vwap in zip(today[-7:-2], vwaps[-7:-2])) >= 4
        feature_base = {"vwap": round(current_vwap, 6), "ema_fast": round(fast, 6),
                        "ema_slow": round(slow, 6), "atr": round(atr, 6)}

        if (fast > slow and current_vwap > vwaps[-1 - self.config.slope_bars]
                and recent_above and abs(prior.low - prior_vwap) <= tolerance
                and current.close > current_vwap):
            stop = min(prior.low, current.close - self.config.stop_atr_multiple * atr)
            risk = current.close - stop
            if risk > 0:
                return Signal(self.strategy_id, Side.LONG, current.timestamp, current.close, stop,
                              current.close + self.config.reward_risk * risk,
                              {**feature_base, "touch": "long_reclaim"})
        if (fast < slow and current_vwap < vwaps[-1 - self.config.slope_bars]
                and recent_below and abs(prior.high - prior_vwap) <= tolerance
                and current.close < current_vwap):
            stop = max(prior.high, current.close + self.config.stop_atr_multiple * atr)
            risk = stop - current.close
            if risk > 0:
                return Signal(self.strategy_id, Side.SHORT, current.timestamp, current.close, stop,
                              current.close - self.config.reward_risk * risk,
                              {**feature_base, "touch": "short_rejection"})
        return None
