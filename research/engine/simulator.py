"""Deterministic next-bar-fill simulator for rejecting weak signal logic.

This is deliberately an underlying-price research simulator, not an options
fill simulator.  It makes no profitability claim for options; option quotes
and fills are required before promotion beyond paper observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Iterable, Sequence

from research.engine.models import Bar, Side, Signal, Trade
from research.engine.strategy import Strategy


@dataclass(frozen=True)
class SimulationConfig:
    starting_capital: float = 5_000.0
    risk_fraction: float = 0.01
    slippage_bps: float = 5.0
    commission_per_unit: float = 0.0
    max_hold_bars: int = 75
    session_exit_time: time | None = None

    def __post_init__(self) -> None:
        if self.starting_capital <= 0 or not 0 < self.risk_fraction <= 0.05:
            raise ValueError("capital must be positive and risk_fraction must be in (0, .05]")
        if self.max_hold_bars < 1 or self.slippage_bps < 0 or self.commission_per_unit < 0:
            raise ValueError("invalid simulation cost or holding configuration")


@dataclass
class _Position:
    signal: Signal
    entry_time: object
    entry_price: float
    quantity: int
    entry_index: int
    best_price: float
    worst_price: float
    active_stop: float


class Simulator:
    """One-position, next-bar-fill simulator with conservative intrabar exits."""

    def __init__(self, config: SimulationConfig = SimulationConfig()) -> None:
        self.config = config

    def run(self, bars: Iterable[Bar], strategy: Strategy) -> list[Trade]:
        completed = list(bars)
        if len(completed) < 3:
            return []

        trades: list[Trade] = []
        history: list[Bar] = []
        position: _Position | None = None
        pending: Signal | None = None
        capital = self.config.starting_capital

        for index, bar in enumerate(completed):
            # Signals emitted at a prior close fill at this open.  They do not
            # get to inspect this bar before committing to the fill.
            if pending is not None:
                position = self._open(pending, bar, index, capital)
                pending = None

            if position is not None and index > position.entry_index:
                close_reason, fill = self._exit_fill(position, bar, index)
                # Intraday studies must not quietly become overnight studies.
                # Stops/targets have priority because they can occur before the
                # closing print inside this bar; otherwise flatten at the
                # configured regular-session exit.
                if close_reason is None and self.config.session_exit_time is not None and bar.timestamp.time() >= self.config.session_exit_time:
                    close_reason, fill = "session", bar.close
                if close_reason is not None:
                    trade = self._close(position, bar, fill, close_reason)
                    trades.append(trade)
                    capital += trade.net_pnl
                    position = None
                else:
                    self._tighten_trailing_stop(strategy, position, bar)

            history.append(bar)
            # Every strategy must see every completed bar, even while its
            # prior signal is in a position.  Stateful indicators (such as
            # recursive EMAs) otherwise resume from stale market state after
            # an exit.  We still discard those in-position signals: one
            # position is the allocation rule, not a reason to stop updating
            # the strategy's market view.
            # ``history`` is owned by this simulator and strategies receive it
            # as a read-only Sequence by contract.  Avoid copying every prior
            # bar into a tuple on every step: research grids otherwise spend
            # most of their time allocating identical history snapshots.
            candidate = strategy.evaluate(history)
            if position is None and pending is None and index < len(completed) - 1:
                pending = candidate

        if position is not None:
            last = completed[-1]
            trades.append(self._close(position, last, last.close, "end_of_data"))
        return trades

    def _open(self, signal: Signal, bar: Bar, index: int, capital: float) -> _Position | None:
        slip = self.config.slippage_bps / 10_000.0
        entry = bar.open * (1 + slip if signal.side is Side.LONG else 1 - slip)
        unit_risk = abs(entry - signal.stop)
        if unit_risk <= 0:
            return None
        quantity = int((capital * self.config.risk_fraction) // unit_risk)
        if quantity < 1:
            return None
        return _Position(signal, bar.timestamp, entry, quantity, index, entry, entry, signal.stop)

    def _exit_fill(self, position: _Position, bar: Bar, index: int) -> tuple[str | None, float]:
        position.best_price = max(position.best_price, bar.high)
        position.worst_price = min(position.worst_price, bar.low)
        s = position.signal
        # Conservative ambiguity rule: if both stop and target touch in one
        # bar, the adverse stop wins.  This avoids imaginary perfect fills.
        if s.side is Side.LONG:
            if bar.low <= position.active_stop:
                return "stop", position.active_stop
            if not s.features.get("no_profit_target", False) and bar.high >= s.target:
                return "target", s.target
        else:
            if bar.high >= position.active_stop:
                return "stop", position.active_stop
            if not s.features.get("no_profit_target", False) and bar.low <= s.target:
                return "target", s.target
        if index - position.entry_index >= self.config.max_hold_bars:
            return "time", bar.close
        return None, 0.0

    @staticmethod
    def _tighten_trailing_stop(strategy: Strategy, position: _Position, bar: Bar) -> None:
        """Apply an optional bar-close trail for the *next* bar only."""
        calculator = getattr(strategy, "trailing_stop", None)
        if not callable(calculator):
            return
        candidate = calculator(position.signal, position.active_stop, bar, position.best_price)
        if candidate is None:
            return
        if position.signal.side is Side.LONG and position.active_stop < candidate < position.signal.target:
            position.active_stop = candidate
        elif position.signal.side is Side.SHORT and position.signal.target < candidate < position.active_stop:
            position.active_stop = candidate

    def _close(self, position: _Position, bar: Bar, raw_exit: float, reason: str) -> Trade:
        slip = self.config.slippage_bps / 10_000.0
        exit_price = raw_exit * (1 - slip if position.signal.side is Side.LONG else 1 + slip)
        sign = 1.0 if position.signal.side is Side.LONG else -1.0
        gross = (exit_price - position.entry_price) * position.quantity * sign
        fees = 2 * position.quantity * self.config.commission_per_unit
        mae = ((position.worst_price - position.entry_price) / position.entry_price * 100
               if position.signal.side is Side.LONG
               else (position.entry_price - position.best_price) / position.entry_price * 100)
        mfe = ((position.best_price - position.entry_price) / position.entry_price * 100
               if position.signal.side is Side.LONG
               else (position.entry_price - position.worst_price) / position.entry_price * 100)
        return Trade(
            strategy_id=position.signal.strategy_id, side=position.signal.side,
            signal_time=position.signal.timestamp, entry_time=position.entry_time,
            exit_time=bar.timestamp, entry_price=position.entry_price, exit_price=exit_price,
            quantity=position.quantity, gross_pnl=round(gross, 4), net_pnl=round(gross - fees, 4),
            mae_pct=round(mae, 4), mfe_pct=round(mfe, 4), exit_reason=reason,
            features=dict(position.signal.features),
        )
