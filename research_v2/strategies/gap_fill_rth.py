"""RTH adaptation of TradingView's open-source IU Gap Fill entry logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Sequence

from research_v2.models import Bar, Side, Signal


def _atr(bars: Sequence[Bar], length: int) -> float | None:
    if len(bars) < length + 1:
        return None
    relevant = bars[-(length + 1):]
    ranges = [max(current.high - current.low, abs(current.high - prior.close), abs(current.low - prior.close))
              for prior, current in zip(relevant, relevant[1:])]
    return sum(ranges) / len(ranges)


@dataclass(frozen=True)
class GapFillRTHConfig:
    min_gap_pct: float = 0.002
    atr_bars: int = 14
    atr_trail_multiple: float = 2.0
    entry_start: time = time(9, 35)
    entry_end: time = time(14, 30)

    def __post_init__(self) -> None:
        if not 0 < self.min_gap_pct < 0.1:
            raise ValueError("min_gap_pct must be in (0, .1)")
        if self.atr_bars < 2 or self.atr_trail_multiple <= 0:
            raise ValueError("ATR configuration is invalid")
        if self.entry_start >= self.entry_end:
            raise ValueError("entry_start must be before entry_end")


class GapFillRTH:
    """Gap-cross-and-reclaim candidate with a bar-close ATR trail."""

    strategy_id = "V2_GAP_FILL_RTH"

    def __init__(self, config: GapFillRTHConfig = GapFillRTHConfig()) -> None:
        self.config = config
        self._seen = 0
        self._last_timestamp = None
        self._history: list[Bar] = []
        self._today: list[Bar] = []
        self._prior_close: float | None = None
        self._session_open: float | None = None

    def _advance(self, bars: Sequence[Bar]) -> None:
        current = bars[-1]
        if len(bars) == self._seen + 1 and (self._seen == 0 or bars[-2].timestamp == self._last_timestamp):
            if self._today and self._today[-1].timestamp.date() == current.timestamp.date():
                self._today.append(current)
            else:
                self._prior_close = self._today[-1].close if self._today else None
                self._today = [current]
                self._session_open = current.open
            self._history.append(current)
        else:
            self._history = list(bars)
            self._today = [bar for bar in bars if bar.timestamp.date() == current.timestamp.date()]
            before_today = [bar for bar in bars if bar.timestamp.date() < current.timestamp.date()]
            self._prior_close = before_today[-1].close if before_today else None
            self._session_open = self._today[0].open if self._today else None
        self._seen, self._last_timestamp = len(bars), current.timestamp

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        self._advance(bars)
        current = bars[-1]
        if (self._prior_close is None or self._session_open is None or len(self._today) <= 1
                or not self.config.entry_start <= current.timestamp.time() <= self.config.entry_end):
            return None
        atr = _atr(self._history, self.config.atr_bars)
        if atr is None or atr <= 0:
            return None
        gap = (self._session_open - self._prior_close) / self._prior_close
        if gap >= self.config.min_gap_pct and current.low < self._prior_close < current.close:
            return self._signal(Side.LONG, current, atr, gap)
        if gap <= -self.config.min_gap_pct and current.high > self._prior_close > current.close:
            return self._signal(Side.SHORT, current, atr, gap)
        return None

    def _signal(self, side: Side, current: Bar, atr: float, gap: float) -> Signal:
        stop = current.close - atr * self.config.atr_trail_multiple if side is Side.LONG else current.close + atr * self.config.atr_trail_multiple
        # The source has no profit target.  The simulator honors this feature
        # and ignores the structurally-required placeholder target.
        target = current.close * (10 if side is Side.LONG else 0.1)
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target,
                      {"gap_pct": round(gap * 100, 4), "atr": round(atr, 6),
                       "atr_trail_multiple": self.config.atr_trail_multiple, "no_profit_target": True,
                       "source": "TradingView IU Gap Fill (RTH adaptation)"})

    def trailing_stop(self, signal: Signal, current_stop: float, bar: Bar, best_price: float) -> float | None:
        atr = _atr(self._history + [bar], self.config.atr_bars)
        if atr is None:
            return None
        if signal.side is Side.LONG:
            return best_price - atr * self.config.atr_trail_multiple
        return best_price + atr * self.config.atr_trail_multiple
