"""Real-quote option markouts for testing whether signals have option value.

This is deliberately *not* a portfolio backtester or a model of Celo's live
exit logic. It answers one narrow, important question using actual quotes:
after a strategy signal, did a conservative near-money option bought at ask
have a positive bid after a fixed holding period?
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from research_v2.models import Bar, Side, Signal
from research_v2.options import OptionQuote, OptionQuoteBook
from research_v2.providers.databento import _open_csv, _parse_symbol, _prices, _timestamp
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


def run_databento_cbbo_markouts(
    bars: Iterable[Bar], raw_paths: Iterable[str | Path], strategy: Strategy,
    underlying: str, hold_minutes: int = 60, max_dte: int = 7,
    max_wait: timedelta = timedelta(minutes=1), max_spread_pct: float = 0.20,
) -> tuple[OptionMarkout, ...]:
    """Run an executable ORB markout directly from Databento CSV files.

    This is the low-memory equivalent of ``run_option_markouts``. Provider
    files can contain millions of option-chain rows, so loading every quote
    into Python is unsafe on the production server. Two sequential passes are
    enough: pass one finds the first eligible quote per contract at entry;
    pass two finds the first bid for the selected contract at the fixed exit.
    It never uses an earlier quote, a midpoint, or a synthetic option price.
    """
    completed = tuple(bars)
    paths = tuple(Path(path) for path in raw_paths)
    expected_underlying = underlying.upper().strip()
    if not completed or not paths or not expected_underlying:
        raise ValueError("bars, raw_paths, and underlying are required")
    if hold_minutes < 1 or max_dte < 0 or max_wait.total_seconds() <= 0 or max_spread_pct <= 0:
        raise ValueError("invalid markout bounds")

    decisions: list[tuple[Signal, Bar, str]] = []
    for signal in strategy_signals(completed, strategy):
        entry_bar = next((bar for bar in completed if bar.timestamp > signal.timestamp), None)
        if entry_bar is not None:
            decisions.append((signal, entry_bar, "call" if signal.side is Side.LONG else "put"))
    if not decisions:
        return ()

    def stream_quotes():
        for raw_path in paths:
            with _open_csv(raw_path) as handle:
                import csv
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "symbol" not in reader.fieldnames:
                    raise ValueError(f"{raw_path.name} is missing Databento symbol column")
                for row in reader:
                    identity = _parse_symbol(row.get("symbol"), expected_underlying)
                    prices = _prices(row)
                    if identity is None or prices is None:
                        continue
                    option_symbol, quote_underlying, expiry_text, strike, option_type = identity
                    yield OptionQuote(
                        datetime.fromisoformat(_timestamp(row)), option_symbol, quote_underlying,
                        datetime.fromisoformat(expiry_text).date(), strike, option_type, *prices,
                    )

    # For each signal and contract retain only the earliest executable entry
    # quote. This is at most one compact object per candidate contract.
    candidates: list[dict[str, OptionQuote]] = [{} for _ in decisions]
    for quote in stream_quotes():
        for index, (_, entry_bar, option_type) in enumerate(decisions):
            if quote.option_type != option_type:
                continue
            if not entry_bar.timestamp <= quote.timestamp <= entry_bar.timestamp + max_wait:
                continue
            dte = (quote.expiration - entry_bar.timestamp.date()).days
            if not 0 <= dte <= max_dte or quote.spread / quote.mid > max_spread_pct:
                continue
            previous = candidates[index].get(quote.option_symbol)
            if previous is None or quote.timestamp < previous.timestamp:
                candidates[index][quote.option_symbol] = quote

    selected: list[OptionQuote | None] = []
    for index, (_, entry_bar, _) in enumerate(decisions):
        usable = candidates[index].values()
        selected.append(min(usable, key=lambda quote: (
            (quote.expiration - entry_bar.timestamp.date()).days,
            abs(quote.strike - entry_bar.open), quote.spread / quote.mid, quote.option_symbol,
        )) if usable else None)

    exits: list[OptionQuote | None] = [None] * len(decisions)
    for quote in stream_quotes():
        for index, (_, entry_bar, _) in enumerate(decisions):
            chosen = selected[index]
            if chosen is None or quote.option_symbol != chosen.option_symbol:
                continue
            exit_target = entry_bar.timestamp + timedelta(minutes=hold_minutes)
            if not exit_target <= quote.timestamp <= exit_target + max_wait:
                continue
            if exits[index] is None or quote.timestamp < exits[index].timestamp:
                exits[index] = quote

    results: list[OptionMarkout] = []
    for index, (signal, entry_bar, _) in enumerate(decisions):
        entry_quote, exit_quote = selected[index], exits[index]
        if entry_quote is None or exit_quote is None:
            continue
        later_bars = [bar for bar in completed if bar.timestamp >= exit_quote.timestamp]
        results.append(OptionMarkout(
            strategy_id=signal.strategy_id, side=signal.side, signal_time=signal.timestamp,
            entry_time=entry_quote.timestamp, exit_time=exit_quote.timestamp,
            contract_symbol=entry_quote.option_symbol, entry_ask=entry_quote.buy_fill(),
            exit_bid=exit_quote.sell_fill(),
            return_pct=round((exit_quote.sell_fill() - entry_quote.buy_fill()) / entry_quote.buy_fill() * 100, 4),
            underlying_entry=entry_bar.open,
            underlying_exit=later_bars[0].close if later_bars else None,
        ))
    return tuple(results)
