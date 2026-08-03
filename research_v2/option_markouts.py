"""Real-quote option markouts for testing whether signals have option value.

This is deliberately *not* a portfolio backtester or a model of Celo's live
exit logic. It answers one narrow, important question using actual quotes:
after a strategy signal, did a conservative near-money option bought at ask
have a positive bid after a fixed holding period?
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from research_v2.models import Bar, Side, Signal
from research_v2.options import OptionQuoteBook
from research_v2.strategy import Strategy


@dataclass(frozen=True)
class OptionMarkout:
    strategy_id: str
    side: Side
    signal_time: object
    entry_time: object
    exit_time: object
    contract_symbol: str
    entry_ask: float
    exit_bid: float
    return_pct: float
    underlying_entry: float
    underlying_exit: float | None


def strategy_signals(bars: Iterable[Bar], strategy: Strategy) -> tuple[Signal, ...]:
    """Generate completed-bar signals without modifying strategy state rules."""
    history: list[Bar] = []
    signals: list[Signal] = []
    for bar in bars:
        history.append(bar)
        signal = strategy.evaluate(tuple(history))
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def run_option_markouts(
    bars: Iterable[Bar], quotes: OptionQuoteBook, strategy: Strategy, underlying: str,
    hold_minutes: int = 60, max_dte: int = 7,
) -> tuple[OptionMarkout, ...]:
    """Evaluate each strategy signal with its next-bar option quote evidence.

    Signals fill no earlier than the next underlying bar. Long signals use a
    call and short signals a put. Each result buys at ask and exits at bid;
    missing/stale quotes are skipped rather than estimated. Overlap is allowed
    because this is a per-signal diagnostic, not an allocation simulation.
    """
    completed = tuple(bars)
    if hold_minutes < 1:
        raise ValueError("hold_minutes must be positive")
    results: list[OptionMarkout] = []
    if not underlying.strip():
        raise ValueError("underlying is required")
    for signal in strategy_signals(completed, strategy):
        next_bars = [bar for bar in completed if bar.timestamp > signal.timestamp]
        if not next_bars:
            continue
        entry_bar = next_bars[0]
        option_type = "call" if signal.side is Side.LONG else "put"
        entry_quote = quotes.select_near_money(
            underlying, option_type, entry_bar.timestamp,
            entry_bar.open, max_dte=max_dte,
        )
        if entry_quote is None:
            continue
        exit_quote = quotes.first_quote_at_or_after(
            entry_quote.option_symbol, entry_bar.timestamp + timedelta(minutes=hold_minutes),
        )
        if exit_quote is None:
            continue
        later_bars = [bar for bar in completed if bar.timestamp >= exit_quote.timestamp]
        underlying_exit = later_bars[0].close if later_bars else None
        results.append(OptionMarkout(
            strategy_id=signal.strategy_id, side=signal.side, signal_time=signal.timestamp,
            entry_time=entry_quote.timestamp, exit_time=exit_quote.timestamp,
            contract_symbol=entry_quote.option_symbol, entry_ask=entry_quote.buy_fill(),
            exit_bid=exit_quote.sell_fill(),
            return_pct=round((exit_quote.sell_fill() - entry_quote.buy_fill()) / entry_quote.buy_fill() * 100, 4),
            underlying_entry=entry_bar.open, underlying_exit=underlying_exit,
        ))
    return tuple(results)
