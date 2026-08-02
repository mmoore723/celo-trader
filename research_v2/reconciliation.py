"""Compare V2 output with an exported TradingView trade list.

This measures fidelity only. A close match says V2 reproduced the declared
rules; it does not establish that those rules are profitable or executable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from research_v2.models import Side, Trade


@dataclass(frozen=True)
class ReferenceTrade:
    side: Side
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float


@dataclass(frozen=True)
class ReconciliationResult:
    reference_count: int
    simulated_count: int
    matched_count: int
    unmatched_reference: int
    unmatched_simulated: int
    mean_entry_price_delta: float

    @property
    def match_rate(self) -> float:
        return self.matched_count / self.reference_count if self.reference_count else 0.0


def _field(row: dict[str, str], *names: str) -> str:
    normalized = {key.strip().lower(): value for key, value in row.items() if key}
    for name in names:
        value = normalized.get(name.lower())
        if value not in (None, ""):
            return value
    raise ValueError(f"TradingView CSV missing one of: {', '.join(names)}")


def _time(value: str, timezone: ZoneInfo) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"unsupported trade timestamp {value!r}; export ISO 8601 timestamps") from exc
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)


def _side(value: str) -> Side:
    text = value.strip().lower()
    if text in {"long", "buy"}:
        return Side.LONG
    if text in {"short", "sell"}:
        return Side.SHORT
    raise ValueError(f"unsupported trade side {value!r}; expected long/short or buy/sell")


def load_tradingview_trades(path: str | Path, timezone_name: str = "America/New_York") -> tuple[ReferenceTrade, ...]:
    """Import a normalized TradingView trade export with explicit field aliases.

    Required semantic fields: entry time, exit time, side, entry price, exit
    price. If a TradingView export uses different labels, normalize it first;
    guessing columns would make the comparison untrustworthy.
    """
    timezone = ZoneInfo(timezone_name)
    records: list[ReferenceTrade] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for number, row in enumerate(reader, start=2):
            try:
                records.append(ReferenceTrade(
                    side=_side(_field(row, "side", "direction", "type")),
                    entry_time=_time(_field(row, "entry time", "entry_time"), timezone),
                    exit_time=_time(_field(row, "exit time", "exit_time"), timezone),
                    entry_price=float(_field(row, "entry price", "entry_price")),
                    exit_price=float(_field(row, "exit price", "exit_price")),
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid TradingView trade at CSV row {number}: {exc}") from exc
    if not records:
        raise ValueError("TradingView trade CSV contains no trades")
    return tuple(records)


def reconcile(
    reference: Sequence[ReferenceTrade], simulated: Sequence[Trade],
    entry_time_tolerance: timedelta = timedelta(minutes=5),
) -> ReconciliationResult:
    """One-to-one match by side and entry time; never silently reorders trades."""
    available = set(range(len(simulated)))
    matched = 0
    deltas: list[float] = []
    for expected in reference:
        candidates = [index for index in available if simulated[index].side is expected.side
                      and abs(simulated[index].entry_time - expected.entry_time) <= entry_time_tolerance]
        if not candidates:
            continue
        index = min(candidates, key=lambda item: abs(simulated[item].entry_time - expected.entry_time))
        available.remove(index)
        matched += 1
        deltas.append(abs(simulated[index].entry_price - expected.entry_price))
    return ReconciliationResult(
        reference_count=len(reference), simulated_count=len(simulated), matched_count=matched,
        unmatched_reference=len(reference) - matched, unmatched_simulated=len(available),
        mean_entry_price_delta=round(sum(deltas) / len(deltas), 6) if deltas else 0.0,
    )
