#!/usr/bin/env python3
"""Test whether the overnight gap changes an opening-drive outcome.

This is the next, deliberately small step after the opening-drive study.
It asks one causal question available by 10:00 ET: did the first-30-minute
move agree with the gap from yesterday's close, oppose it, or begin from a
nearly flat gap?  It reports continuation outcomes to 11:30 separately in
frozen train and holdout periods.  It is not a trading strategy.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv


OPENING_SLOTS = (time(9, 30), time(9, 35), time(9, 40), time(9, 45), time(9, 50), time(9, 55))
ENTRY_TIME, EXIT_TIME = time(10, 0), time(11, 30)
MIN_OPENING_MOVE, MIN_GAP = 0.005, 0.001
CONTEXTS = ("gap_aligned", "gap_opposed", "gap_neutral")


def _summary(values: list[float]) -> dict[str, int | float | None]:
    if not values:
        return {"observations": 0, "win_rate_pct": None, "average_continuation_pct": None}
    return {
        "observations": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 1),
        "average_continuation_pct": round(mean(values) * 100, 4),
    }


def _study(path: Path, split: datetime) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    bars = load_csv(path).bars
    sessions: dict[object, dict[time, object]] = defaultdict(dict)
    for bar in bars:
        sessions[bar.timestamp.date()][bar.timestamp.time()] = bar
    ordered = sorted(sessions.items())
    train = {context: [] for context in CONTEXTS}
    holdout = {context: [] for context in CONTEXTS}
    prior_close: float | None = None
    for _, session in ordered:
        opening = [session.get(slot) for slot in OPENING_SLOTS]
        entry, exit_ = session.get(ENTRY_TIME), session.get(EXIT_TIME)
        day_last = max(session.values(), key=lambda bar: bar.timestamp) if session else None
        if any(bar is None for bar in opening) or entry is None or exit_ is None or prior_close is None:
            prior_close = day_last.close if day_last else prior_close
            continue
        assert entry is not None and exit_ is not None
        opening_move = (opening[-1].close - opening[0].open) / opening[0].open
        gap = (opening[0].open - prior_close) / prior_close
        if abs(opening_move) < MIN_OPENING_MOVE:
            prior_close = day_last.close if day_last else prior_close
            continue
        if abs(gap) < MIN_GAP:
            context = "gap_neutral"
        elif (opening_move > 0) == (gap > 0):
            context = "gap_aligned"
        else:
            context = "gap_opposed"
        continuation = (1 if opening_move > 0 else -1) * (exit_.open - entry.open) / entry.open
        (train if entry.timestamp < split else holdout)[context].append(continuation)
        prior_close = day_last.close if day_last else prior_close
    return train, holdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="TICKER=CSV")
    parser.add_argument("--split", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    pooled_train = {context: [] for context in CONTEXTS}
    pooled_holdout = {context: [] for context in CONTEXTS}
    symbols: dict[str, dict] = {}
    for item in args.input:
        if "=" not in item:
            parser.error("--input must be TICKER=CSV")
        ticker, raw_path = item.split("=", 1)
        train, holdout = _study(Path(raw_path), split)
        symbols[ticker.upper()] = {
            "train": {context: _summary(values) for context, values in train.items()},
            "holdout": {context: _summary(values) for context, values in holdout.items()},
        }
        for context in CONTEXTS:
            pooled_train[context].extend(train[context])
            pooled_holdout[context].extend(holdout[context])
    payload = {
        "purpose": "Opening-drive gap-context study only; no strategy, quote, or trade action.",
        "fixed_design": {
            "opening_move_min_pct": MIN_OPENING_MOVE * 100, "gap_neutral_below_pct": MIN_GAP * 100,
            "entry_reference": "10:00 open", "exit_reference": "11:30 open",
        },
        "split": split.isoformat(), "symbols": symbols,
        "pooled": {
            "train": {context: _summary(values) for context, values in pooled_train.items()},
            "holdout": {context: _summary(values) for context, values in pooled_holdout.items()},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
