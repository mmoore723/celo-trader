"""Vendor-neutral historical option-quote contract for V2 research.

This module intentionally has no provider credentials and cannot submit an
order.  It provides the minimum executable evidence an options backtest needs:
time-stamped bid/ask, contract identity, and optional IV/Greeks.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime, date
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
