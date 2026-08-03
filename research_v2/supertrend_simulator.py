"""Next-bar reversal-fill simulator for the exact TradingView SuperTrend source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Iterable

from research_v2.models import Bar, Side, Trade
from research_v2.strategies.supertrend_reversal import SuperTrendReversal


@dataclass(frozen=True)
class ReversalSimulationConfig:
    quantity: int = 1
    slippage_bps: float = 5.0
    commission_per_unit: float = 0.0
    session_exit_time: time | None = time(15, 55)

    def __post_init__(self) -> None:
        if self.quantity < 1 or self.slippage_bps < 0 or self.commission_per_unit < 0:
            raise ValueError("invalid reversal simulation configuration")


@dataclass
class _OpenReversal:
    side: Side
    signal_time: object
    entry_time: object
    entry_price: float
    best_price: float
    worst_price: float
    features: dict


class SuperTrendReversalSimulator:
    """Models Pine's default next-bar fills and opposite-signal reversals.

    This deliberately uses one underlying unit, as the published ``strategy``
    call has no quantity, cost, or capital parameters.  It is a source-fidelity
    test, not an options profitability model.
    """

    def __init__(self, config: ReversalSimulationConfig = ReversalSimulationConfig()) -> None:
        self.config = config

    def run(self, bars: Iterable[Bar], strategy: SuperTrendReversal) -> list[Trade]:
        completed = list(bars)
        trades: list[Trade] = []
        history: list[Bar] = []
        position: _OpenReversal | None = None
        pending = None
        for index, bar in enumerate(completed):
            at_session_exit = (self.config.session_exit_time is not None
                               and bar.timestamp.time() >= self.config.session_exit_time)
            if pending is not None:
                # An intraday option position cannot open at the closing bar
                # only to be flattened immediately.  Discard that pending
                # signal instead of borrowing an overnight position.
                if at_session_exit:
                    pending = None
                elif position is not None and position.side is not pending.side:
                    trades.append(self._close(position, bar, self._exit_price(position.side, bar.open), "opposite_flip"))
                    position = None
                if pending is not None and position is None:
                    position = _OpenReversal(pending.side, pending.timestamp, bar.timestamp,
                                             self._entry_price(pending.side, bar.open), bar.open, bar.open,
                                             dict(pending.features))
                pending = None
            if position is not None and index > 0:
                position.best_price = max(position.best_price, bar.high)
                position.worst_price = min(position.worst_price, bar.low)
                if at_session_exit:
                    trades.append(self._close(position, bar, self._exit_price(position.side, bar.close), "session"))
                    position = None
            history.append(bar)
            if not at_session_exit and index < len(completed) - 1:
                signal = strategy.evaluate(tuple(history))
                if signal is not None and (position is None or signal.side is not position.side):
                    pending = signal
        if position is not None:
            trades.append(self._close(position, completed[-1], self._exit_price(position.side, completed[-1].close), "end_of_data"))
        return trades

    def _entry_price(self, side: Side, raw: float) -> float:
        slip = self.config.slippage_bps / 10_000.0
        return raw * (1 + slip if side is Side.LONG else 1 - slip)

    def _exit_price(self, side: Side, raw: float) -> float:
        slip = self.config.slippage_bps / 10_000.0
        return raw * (1 - slip if side is Side.LONG else 1 + slip)

    def _close(self, position: _OpenReversal, bar: Bar, exit_price: float, reason: str) -> Trade:
        sign = 1.0 if position.side is Side.LONG else -1.0
        gross = (exit_price - position.entry_price) * self.config.quantity * sign
        fees = 2 * self.config.quantity * self.config.commission_per_unit
        mae = ((position.worst_price - position.entry_price) / position.entry_price * 100
               if position.side is Side.LONG else (position.entry_price - position.best_price) / position.entry_price * 100)
        mfe = ((position.best_price - position.entry_price) / position.entry_price * 100
               if position.side is Side.LONG else (position.entry_price - position.worst_price) / position.entry_price * 100)
        return Trade("TV_SUPERTREND_REVERSAL_V4", position.side, position.signal_time, position.entry_time,
                     bar.timestamp, position.entry_price, exit_price, self.config.quantity, round(gross, 4),
                     round(gross - fees, 4), round(mae, 4), round(mfe, 4), reason, position.features)
