#!/usr/bin/env python3
"""Build a causal, explainable 10:00 ET intraday research dataset.

Each row represents one possible decision at 10:00 ET.  Feature columns use
only completed information available then; outcome columns describe the move
from the 10:00 open to the 11:30 open and must never be used as inputs.  This
file is a research artifact for walk-forward modelling, not a trade command.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv


OPENING_SLOTS = (time(9, 30), time(9, 35), time(9, 40), time(9, 45), time(9, 50), time(9, 55))
ENTRY_TIME, EXIT_TIME = time(10, 0), time(11, 30)
FIELDS = (
    "timestamp", "ticker", "opening_move_pct", "opening_range_pct", "gap_pct",
    "gap_aligned", "prior_day_return_pct", "prior_day_range_pct", "relative_opening_volume",
    "outcome_forward_return_pct", "outcome_forward_direction",
)


def _daily_sessions(path: Path) -> list[dict]:
    bars = load_csv(path).bars
    grouped: dict[object, dict[time, object]] = defaultdict(dict)
    for bar in bars:
        grouped[bar.timestamp.date()][bar.timestamp.time()] = bar
    sessions: list[dict] = []
    for day, session in sorted(grouped.items()):
        first = session.get(time(9, 30))
        last = max(session.values(), key=lambda bar: bar.timestamp) if session else None
        if first is None or last is None:
            continue
        sessions.append({"day": day, "bars": session, "open": first.open, "close": last.close,
                         "high": max(bar.high for bar in session.values()), "low": min(bar.low for bar in session.values())})
    return sessions


def _rows(ticker: str, path: Path) -> list[dict[str, object]]:
    sessions = _daily_sessions(path)
    rows: list[dict[str, object]] = []
    opening_volumes: list[float] = []
    daily_returns: list[float] = []
    daily_ranges: list[float] = []
    for index, session in enumerate(sessions):
        bars = session["bars"]
        opening = [bars.get(slot) for slot in OPENING_SLOTS]
        entry, exit_ = bars.get(ENTRY_TIME), bars.get(EXIT_TIME)
        if (index < 20 or any(bar is None for bar in opening) or entry is None or exit_ is None):
            if not any(bar is None for bar in opening):
                opening_volumes.append(sum(bar.volume for bar in opening))
            if index:
                prior_close = sessions[index - 1]["close"]
                daily_returns.append((session["close"] - prior_close) / prior_close)
            daily_ranges.append((session["high"] - session["low"]) / session["open"])
            continue
        assert entry is not None and exit_ is not None
        prior = sessions[index - 1]
        opening_move = (opening[-1].close - opening[0].open) / opening[0].open
        opening_range = (max(bar.high for bar in opening) - min(bar.low for bar in opening)) / opening[0].open
        gap = (opening[0].open - prior["close"]) / prior["close"]
        opening_volume = sum(bar.volume for bar in opening)
        relative_volume = opening_volume / max(mean(opening_volumes[-20:]), 1.0)
        forward = (exit_.open - entry.open) / entry.open
        rows.append({
            "timestamp": entry.timestamp.isoformat(), "ticker": ticker,
            "opening_move_pct": round(opening_move * 100, 6), "opening_range_pct": round(opening_range * 100, 6),
            "gap_pct": round(gap * 100, 6),
            "gap_aligned": int(abs(gap) >= 0.001 and ((gap > 0) == (opening_move > 0))),
            "prior_day_return_pct": round(mean(daily_returns[-5:]) * 100, 6),
            "prior_day_range_pct": round(mean(daily_ranges[-5:]) * 100, 6),
            "relative_opening_volume": round(relative_volume, 6),
            "outcome_forward_return_pct": round(forward * 100, 6),
            "outcome_forward_direction": int(forward > 0) - int(forward < 0),
        })
        opening_volumes.append(opening_volume)
        daily_returns.append((session["close"] - prior["close"]) / prior["close"])
        daily_ranges.append((session["high"] - session["low"]) / session["open"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="TICKER=CSV")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    for item in args.input:
        if "=" not in item:
            parser.error("--input must be TICKER=CSV")
        ticker, raw_path = item.split("=", 1)
        rows.extend(_rows(ticker.upper().strip(), Path(raw_path)))
    rows.sort(key=lambda row: row["timestamp"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row["ticker"])] += 1
    print(f"saved {len(rows)} causal decision rows to {args.output}; "
          + ", ".join(f"{ticker}={count}" for ticker, count in sorted(counts.items())))


if __name__ == "__main__":
    main()
