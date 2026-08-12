#!/usr/bin/env python3
"""Measure a fixed opening-drive rule across pre-declared holding horizons.

This is deliberately a market study, not a backtest or a trade command.  At
10:00 ET it knows only the completed first thirty minutes.  It then evaluates
the *same* direction (continuation or reversal) at fixed later times.  Train
and untouched holdout data are always reported separately so we do not choose
a holding time only because it looked good in the final year.
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
ENTRY_TIME = time(10, 0)
# Declared before seeing this study's output: a short confirmation, the
# previous 11:30 research target, an afternoon check, and the regular-session
# close proxy.  No result changes this list.
EXIT_TIMES = (time(10, 30), time(11, 30), time(13, 0), time(15, 55))
MOVE_BANDS = (0.0025, 0.0050)


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"observations": 0, "win_rate_pct": None, "average_return_pct": None}
    return {
        "observations": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 1),
        "average_return_pct": round(mean(values) * 100, 4),
    }


def _new_bucket() -> dict[str, dict[str, list[float]]]:
    return {str(band): {exit_time.isoformat(timespec="minutes"): [] for exit_time in EXIT_TIMES} for band in MOVE_BANDS}


def _observations(path: Path, split: datetime) -> tuple[dict, dict]:
    by_day: dict[object, dict[time, object]] = defaultdict(dict)
    for bar in load_csv(path).bars:
        by_day[bar.timestamp.date()][bar.timestamp.time()] = bar
    train, holdout = _new_bucket(), _new_bucket()
    for session in by_day.values():
        opening = [session.get(slot) for slot in OPENING_SLOTS]
        entry = session.get(ENTRY_TIME)
        exits = {exit_time: session.get(exit_time) for exit_time in EXIT_TIMES}
        if any(bar is None for bar in opening) or entry is None or any(bar is None for bar in exits.values()):
            continue
        assert entry is not None
        opening_move = (opening[-1].close - opening[0].open) / opening[0].open
        bucket = train if entry.timestamp < split else holdout
        for band in MOVE_BANDS:
            if abs(opening_move) < band:
                continue
            direction = 1 if opening_move > 0 else -1
            for exit_time, exit_bar in exits.items():
                assert exit_bar is not None
                forward = (exit_bar.open - entry.open) / entry.open
                bucket[str(band)][exit_time.isoformat(timespec="minutes")].append(direction * forward)
    return train, holdout


def _report(bucket: dict) -> dict:
    return {band: {exit_time: _summary(values) for exit_time, values in horizons.items()}
            for band, horizons in bucket.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="TICKER=CSV")
    parser.add_argument("--split", required=True, help="ISO timestamp; later entries form untouched holdout")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    parsed: list[tuple[str, Path]] = []
    for item in args.input:
        if "=" not in item:
            parser.error("--input must be TICKER=CSV")
        ticker, raw_path = item.split("=", 1)
        parsed.append((ticker.upper().strip(), Path(raw_path)))

    per_symbol: dict[str, dict] = {}
    pooled_train, pooled_holdout = _new_bucket(), _new_bucket()
    for ticker, path in parsed:
        train, holdout = _observations(path, split)
        per_symbol[ticker] = {"path": str(path), "train": _report(train), "holdout": _report(holdout)}
        for band in pooled_train:
            for exit_time in pooled_train[band]:
                pooled_train[band][exit_time].extend(train[band][exit_time])
                pooled_holdout[band][exit_time].extend(holdout[band][exit_time])
    payload = {
        "purpose": "Fixed-horizon opening-drive market study only; no strategy, options quote, or trading action.",
        "fixed_design": {
            "opening_window": "09:30-10:00 ET", "entry_reference": "10:00 open",
            "direction": "continuation of the first 30-minute move", "exit_references": [item.isoformat(timespec="minutes") for item in EXIT_TIMES],
            "opening_move_bands_pct": [round(band * 100, 2) for band in MOVE_BANDS],
        },
        "split": split.isoformat(), "symbols": per_symbol,
        "pooled": {"train": _report(pooled_train), "holdout": _report(pooled_holdout)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
