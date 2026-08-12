"""RTH adaptation of a 20-bar Turtle Soup false-breakout setup.

The setup first sweeps a prior 20-bar extreme.  The *next* completed bar must
then reclaim the old level: after a downside sweep it closes back above the
prior low, and after an upside sweep it closes back below the prior high.
That is the actual false-breakout proof.  Requiring price to close beyond the
entire sweep candle would turn this into a much rarer momentum reversal and
would not test the intended setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from research.engine.models import Bar, Side, Signal


@dataclass(frozen=True)
class TurtleSoupRTHConfig:
    lookback_bars: int = 20
    target_risk_ratio: float = 1.5
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)

    def __post_init__(self) -> None:
        if self.lookback_bars < 5:
            raise ValueError("lookback_bars must be at least 5")
        if self.target_risk_ratio <= 1:
            raise ValueError("target_risk_ratio must be greater than one")
        if self.entry_start >= self.entry_end:
            raise ValueError("entry_start must be before entry_end")


class TurtleSoupRTH:
    """One-sweep, next-bar-confirmed false-breakout reversal hypothesis."""

    strategy_id = "V2_TURTLE_SOUP_RTH"

    def __init__(self, config: TurtleSoupRTHConfig = TurtleSoupRTHConfig()) -> None:
        self.config = config
        self._seen = 0
        self._last_timestamp = None
        self._today: list[Bar] = []
        self._state: Side | None = None
        self._setup_high: float | None = None
        self._setup_low: float | None = None
        self._reclaim_level: float | None = None
        self._setup_index: int | None = None

    def _session(self, bars: Sequence[Bar]) -> list[Bar]:
        current = bars[-1]
        if len(bars) == self._seen + 1 and (self._seen == 0 or bars[-2].timestamp == self._last_timestamp):
            if self._today and self._today[-1].timestamp.date() == current.timestamp.date():
                self._today.append(current)
            else:
                self._today = [current]
                self._reset_setup()
        else:
            self._today = [bar for bar in bars if bar.timestamp.date() == current.timestamp.date()]
            self._reset_setup()
        self._seen, self._last_timestamp = len(bars), current.timestamp
        return self._today

    def _reset_setup(self) -> None:
        self._state = None
        self._setup_high = self._setup_low = None
        self._reclaim_level = None
        self._setup_index = None

    def _emit(self, side: Side, current: Bar) -> Signal:
        assert self._setup_high is not None and self._setup_low is not None
        if side is Side.LONG:
            stop = self._setup_low
            target = current.close + (current.close - stop) * self.config.target_risk_ratio
        else:
            stop = self._setup_high
            target = current.close - (stop - current.close) * self.config.target_risk_ratio
        return Signal(self.strategy_id, side, current.timestamp, current.close, stop, target,
                      {"lookback_bars": self.config.lookback_bars,
                       "target_risk_ratio": self.config.target_risk_ratio,
                       "source": "TradingView Pridarasx Turtle Soup 1-Bar Confirmation (RTH exit adaptation)"})

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        today = self._session(bars)
        current = today[-1]

        # The source permits one—and only one—bar for the reversal to prove
        # itself.  The confirmation bar cannot become another setup.
        if self._state is not None:
            assert self._setup_index is not None
            if len(today) == self._setup_index + 1:
                side = self._state
                assert self._reclaim_level is not None
                confirmed = ((side is Side.LONG and current.close > self._reclaim_level)
                             or (side is Side.SHORT and current.close < self._reclaim_level))
                if confirmed and self.config.entry_start <= current.timestamp.time() <= self.config.entry_end:
                    signal = self._emit(side, current)
                    self._reset_setup()
                    return signal
            self._reset_setup()
            return None

        if len(today) <= self.config.lookback_bars:
            return None
        prior = today[-(self.config.lookback_bars + 1):-1]
        highest = max(bar.high for bar in prior)
        lowest = min(bar.low for bar in prior)
        if current.low < lowest:
            self._state, self._setup_high, self._setup_low = Side.LONG, current.high, current.low
            self._reclaim_level = lowest
            self._setup_index = len(today)
        elif current.high > highest:
            self._state, self._setup_high, self._setup_low = Side.SHORT, current.high, current.low
            self._reclaim_level = highest
            self._setup_index = len(today)
        return None
