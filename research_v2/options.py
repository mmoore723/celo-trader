"""Vendor-neutral historical option-quote contract for V2 research.

This module intentionally has no provider credentials and cannot submit an
order.  It provides the minimum executable evidence an options backtest needs:
time-stamped bid/ask, contract identity, and optional IV/Greeks.
"""
from __future__ import annotations
import csv
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Literal

OptionType = Literal["call", "put"]

@dataclass(frozen=True)
class OptionQuote:
    timestamp: datetime
    option_symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: OptionType
    bid: float
    ask: float
    iv: float | None = None
    delta: float | None = None
    open_interest: int | None = None

    def __post_init__(self) -> None:
        if not self.option_symbol or not self.underlying or self.strike <= 0 or self.bid < 0 or self.ask < self.bid:
            raise ValueError("invalid option quote identity or bid/ask")
        if self.option_type not in {"call", "put"}:
            raise ValueError("option_type must be call or put")

    @property
    def spread(self) -> float: return self.ask - self.bid
    @property
    def mid(self) -> float: return (self.bid + self.ask) / 2

    def buy_fill(self) -> float: return self.ask
    def sell_fill(self) -> float: return self.bid


class OptionQuoteBook:
    """Point-in-time, bid/ask-only option execution evidence.

    It never interpolates a price. A buy is executable only at a quote's ask;
    a sell is executable only at that same contract's bid. This is intentionally
    smaller than a backtester—it is the safe quote-selection primitive that a
    real options simulation can build upon.
    """
    def __init__(self, quotes: tuple[OptionQuote, ...]):
        if not quotes:
            raise ValueError("option quote book requires quotes")
        self._by_symbol: dict[str, tuple[OptionQuote, ...]] = {}
        self._timestamps: dict[str, tuple[datetime, ...]] = {}
        grouped: dict[str, list[OptionQuote]] = {}
        for quote in quotes:
            grouped.setdefault(quote.option_symbol, []).append(quote)
        for symbol, rows in grouped.items():
            ordered = tuple(sorted(rows, key=lambda quote: quote.timestamp))
            self._by_symbol[symbol] = ordered
            self._timestamps[symbol] = tuple(quote.timestamp for quote in ordered)

    def first_quote_at_or_after(
        self, symbol: str, timestamp: datetime, max_wait: timedelta = timedelta(minutes=1),
    ) -> OptionQuote | None:
        """Return first usable quote after a decision, never an earlier quote."""
        rows = self._by_symbol.get(symbol)
        if not rows:
            return None
        index = bisect_left(self._timestamps[symbol], timestamp)
        if index >= len(rows):
            return None
        quote = rows[index]
        return quote if quote.timestamp <= timestamp + max_wait else None

    def select_near_money(
        self, underlying: str, option_type: OptionType, timestamp: datetime,
        underlying_price: float, max_dte: int = 7,
        max_wait: timedelta = timedelta(minutes=1), max_spread_pct: float = 0.20,
    ) -> OptionQuote | None:
        """Choose an executable near-money quote using only information then known.

        The selection is deliberately conservative: nearest expiry, then
        nearest strike, then narrowest percentage spread. It is suitable only
        as an explicit baseline for research, not as a claim of optimal option
        contract selection.
        """
        if underlying_price <= 0 or max_dte < 0 or max_spread_pct <= 0:
            raise ValueError("invalid option-selection bounds")
        candidates: list[OptionQuote] = []
        for symbol, rows in self._by_symbol.items():
            # A quote cannot be selected unless it is available after the
            # decision; never peek at an earlier or later end-of-bar close.
            quote = self.first_quote_at_or_after(symbol, timestamp, max_wait)
            if quote is None or quote.underlying != underlying.upper() or quote.option_type != option_type:
                continue
            dte = (quote.expiration - timestamp.date()).days
            if not 0 <= dte <= max_dte or quote.spread / quote.mid > max_spread_pct:
                continue
            candidates.append(quote)
        if not candidates:
            return None
        return min(candidates, key=lambda quote: (
            (quote.expiration - timestamp.date()).days,
            abs(quote.strike - underlying_price), quote.spread / quote.mid, quote.option_symbol,
        ))

def load_option_quotes(path: str | Path) -> tuple[OptionQuote, ...]:
    """Load chronological vendor-export CSV; reject ambiguous fill inputs.

    Required columns: timestamp, option_symbol, underlying, expiration,
    strike, option_type, bid, ask. Optional: iv, delta, open_interest.
    """
    required = {"timestamp", "option_symbol", "underlying", "expiration", "strike", "option_type", "bid", "ask"}
    output: list[OptionQuote] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("option quote CSV is missing required columns")
        for number, row in enumerate(reader, start=2):
            try:
                optional_float = lambda key: float(row[key]) if row.get(key) not in {None, ""} else None
                optional_int = lambda key: int(row[key]) if row.get(key) not in {None, ""} else None
                output.append(OptionQuote(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")), row["option_symbol"],
                    row["underlying"].upper(), date.fromisoformat(row["expiration"]), float(row["strike"]),
                    row["option_type"].lower(), float(row["bid"]), float(row["ask"]), optional_float("iv"),
                    optional_float("delta"), optional_int("open_interest")))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid option quote at CSV row {number}: {exc}") from exc
    if not output or [quote.timestamp for quote in output] != sorted(quote.timestamp for quote in output):
        raise ValueError("option quote CSV must be nonempty and chronological")
    return tuple(output)
