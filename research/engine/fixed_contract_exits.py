"""Price preselected option contracts at real post-decision bids."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from research.engine.exit_rules import PlannedExit
from research.engine.providers.databento import _open_csv, _prices, _timestamp


@dataclass(frozen=True)
class ExactContractEpisode:
    signal_time: datetime
    entry_time: datetime
    contract: str
    entry_ask: float


def price_exact_contract_exits(
    raw_path: str | Path, episode: ExactContractEpisode,
    plans: Mapping[str, PlannedExit], *, max_wait: timedelta = timedelta(minutes=1),
) -> dict[str, dict[str, object]]:
    """Return the first real bid for each exit without reselecting the option.

    Entry contract, time, and ask are immutable inputs from the original paid
    study.  Rows with no positive executable bid inside the declared window
    remain absent; no midpoint or synthetic price is substituted.
    """
    if episode.entry_ask <= 0 or max_wait.total_seconds() <= 0 or not plans:
        raise ValueError("valid entry and exit plans are required")
    pending = {
        label: (plan.time, plan.time + max_wait)
        for label, plan in plans.items()
    }
    found: dict[str, tuple[datetime, float]] = {}
    with _open_csv(Path(raw_path)) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "symbol" not in reader.fieldnames:
            raise ValueError(f"{Path(raw_path).name} is missing Databento symbol column")
        for row in reader:
            if str(row.get("symbol") or "").strip() != episode.contract.strip():
                continue
            try:
                timestamp = datetime.fromisoformat(_timestamp(row))
            except ValueError:
                continue
            prices = _prices(row)
            if prices is None:
                continue
            bid, _ = prices
            for label, (target, deadline) in pending.items():
                if label not in found and target <= timestamp <= deadline:
                    found[label] = (timestamp, bid)
            if len(found) == len(pending):
                break
    return {
        label: {
            "signal_time": episode.signal_time.isoformat(),
            "entry_time": episode.entry_time.isoformat(),
            "exit_time": timestamp.isoformat(),
            "contract": episode.contract,
            "entry_ask": episode.entry_ask,
            "exit_bid": bid,
            "gross_return_pct": round((bid - episode.entry_ask) / episode.entry_ask * 100, 6),
            "exit_reason": plans[label].reason,
            "exit_quote_delay_seconds": round(
                (timestamp - plans[label].time).total_seconds(), 3,
            ),
        }
        for label, (timestamp, bid) in found.items()
    }
