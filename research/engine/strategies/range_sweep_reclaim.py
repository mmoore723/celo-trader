"""Causal, order-free range-sweep reclaim research strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal
from research.engine.strategies.trend_continuation import _atr
from research.engine.strategies.vwap_pullback import _session, _vwaps


def efficiency_ratio(closes: Sequence[float]) -> float:
    """Return directional travel divided by total travel."""
    if len(closes) < 2:
        raise ValueError("efficiency ratio requires at least two closes")
    travel = sum(abs(current - prior) for prior, current in zip(closes, closes[1:]))
    return 0.0 if travel == 0 else abs(closes[-1] - closes[0]) / travel


@dataclass(frozen=True)
class RangeSweepReclaimConfig:
    range_bars: int = 20
    atr_bars: int = 14
    maximum_efficiency: float = 0.35
    minimum_sweep_atr: float = 0.10
    minimum_vwap_room_atr: float = 0.35
    stop_atr: float = 0.25
    minimum_reward_risk: float = 1.0
    rearm_distance_atr: float = 0.20
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)

    def __post_init__(self) -> None:
        if self.range_bars < 5 or self.atr_bars < 2:
            raise ValueError("range and ATR windows must be usable")
        if not 0 < self.maximum_efficiency < 1:
            raise ValueError("maximum efficiency must be between zero and one")
        if min(self.minimum_sweep_atr, self.minimum_vwap_room_atr, self.stop_atr) < 0:
            raise ValueError("sweep, room, and stop distances must be non-negative")
        if self.minimum_reward_risk <= 0 or self.rearm_distance_atr < 0:
            raise ValueError("reward/risk must be positive and rearm distance non-negative")
        if self.entry_start >= self.entry_end:
            raise ValueError("entry window must have positive duration")


class RangeSweepReclaim:
    """Find confirmed false range breaks after a quiet intraday period."""

    strategy_id = "V2_RANGE_SWEEP_RECLAIM"

    def __init__(self, config: RangeSweepReclaimConfig = RangeSweepReclaimConfig()) -> None:
        self.config = config
        self._day: date | None = None
        self._long_armed = True
        self._short_armed = True

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = _session(bars)
        if not today:
            return None
        current = today[-1]
        if current.timestamp.date() != self._day:
            self._day = current.timestamp.date()
            self._long_armed = self._short_armed = True

        minimum = max(self.config.atr_bars + 3, self.config.range_bars + 3)
        if len(today) < minimum or not self.config.entry_start <= current.timestamp.time() <= self.config.entry_end:
            return None

        context = today[-(self.config.range_bars + 2):-2]
        prior, current = today[-2], today[-1]
        atr = _atr(today[:-1], self.config.atr_bars)
        ratio = efficiency_ratio([bar.close for bar in context])
        if atr <= 0 or ratio > self.config.maximum_efficiency:
            return None
        range_high = max(bar.high for bar in context)
        range_low = min(bar.low for bar in context)
        vwap = _vwaps(today)[-1]

        if current.close >= vwap - atr * self.config.rearm_distance_atr:
            self._long_armed = True
        if current.close <= vwap + atr * self.config.rearm_distance_atr:
            self._short_armed = True

        if (
            self._long_armed
            and prior.low <= range_low - atr * self.config.minimum_sweep_atr
            and current.close > range_low
            and current.close > current.open
            and current.close < vwap
        ):
            stop = min(prior.low, current.low) - atr * self.config.stop_atr
            reward, risk = vwap - current.close, current.close - stop
            if (
                reward >= atr * self.config.minimum_vwap_room_atr
                and risk > 0
                and reward >= risk * self.config.minimum_reward_risk
            ):
                self._long_armed = False
                return Signal(
                    self.strategy_id, Side.LONG, current.timestamp, current.close, stop, vwap,
                    {
                        "trigger": "quiet_range_low_swept_then_reclaimed",
                        "range_low": round(range_low, 6),
                        "range_high": round(range_high, 6),
                        "vwap": round(vwap, 6),
                        "atr": round(atr, 6),
                        "efficiency_ratio": round(ratio, 6),
                    },
                )

        if (
            self._short_armed
            and prior.high >= range_high + atr * self.config.minimum_sweep_atr
            and current.close < range_high
            and current.close < current.open
            and current.close > vwap
        ):
            stop = max(prior.high, current.high) + atr * self.config.stop_atr
            reward, risk = current.close - vwap, stop - current.close
            if (
                reward >= atr * self.config.minimum_vwap_room_atr
                and risk > 0
                and reward >= risk * self.config.minimum_reward_risk
            ):
                self._short_armed = False
                return Signal(
                    self.strategy_id, Side.SHORT, current.timestamp, current.close, stop, vwap,
                    {
                        "trigger": "quiet_range_high_swept_then_reclaimed",
                        "range_low": round(range_low, 6),
                        "range_high": round(range_high, 6),
                        "vwap": round(vwap, 6),
                        "atr": round(atr, 6),
                        "efficiency_ratio": round(ratio, 6),
                    },
                )
        return None


class LongOnlyRangeSweepReclaim:
    """Replay the session causally and expose only the tested call setup."""

    strategy_id = RangeSweepReclaim.strategy_id

    def __init__(self, config: RangeSweepReclaimConfig = RangeSweepReclaimConfig()) -> None:
        self.config = config

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        if not bars:
            return None
        current_date = bars[-1].timestamp.date()
        start = len(bars) - 1
        while start and bars[start - 1].timestamp.date() == current_date:
            start -= 1
        strategy = RangeSweepReclaim(self.config)
        latest: Signal | None = None
        for end in range(start + 1, len(bars) + 1):
            candidate = strategy.evaluate(bars[:end])
            if candidate is not None:
                latest = candidate
        if latest is not None and latest.timestamp == bars[-1].timestamp and latest.side is Side.LONG:
            return latest
        return None
