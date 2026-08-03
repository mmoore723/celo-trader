#!/usr/bin/env python3
"""Measure opening-drive continuation versus reversal before writing a strategy.

At 10:00 ET, after the first 30 minutes are complete, this measures the
underlying move through 11:30 ET.  It uses fixed, declared opening-move bands
and reports train and untouched-holdout results separately.  This is a market
study, not a backtest: it has no broker, options pricing, position sizing, or
order capability.
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

from research_v2.data import load_csv


OPENING_SLOTS = (time(9, 30), time(9, 35), time(9, 40), time(9, 45), time(9, 50), time(9, 55))
ENTRY_TIME, EXIT_TIME = time(10, 0), time(11, 30)
MOVE_BANDS = (0.0025, 0.0050, 0.0075)


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"observations": 0, "win_rate_pct": None, "average_return_pct": None}
    return {
        "observations": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 1),
        "average_return_pct": round(mean(values) * 100, 4),
    }


def _observations(path: Path, split: datetime) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    bars = load_csv(path).bars
    by_day: dict[object, dict[time, object]] = defaultdict(dict)
    for bar in bars:
        by_day[bar.timestamp.date()][bar.timestamp.time()] = bar
    train: dict[str, list[dict]] = {str(band): [] for band in MOVE_BANDS}
    holdout: dict[str, list[dict]] = {str(band): [] for band in MOVE_BANDS}
    for session in by_day.values():
        opening = [session.get(slot) for slot in OPENING_SLOTS]
        entry, exit_ = session.get(ENTRY_TIME), session.get(EXIT_TIME)
        if any(bar is None for bar in opening) or entry is None or exit_ is None:
            continue
        assert entry is not None and exit_ is not None
        opening_open = opening[0].open
        opening_close = opening[-1].close
        opening_move = (opening_close - opening_open) / opening_open
        forward_return = (exit_.open - entry.open) / entry.open
        bucket = train if entry.timestamp < split else holdout
        for band in MOVE_BANDS:
            if abs(opening_move) >= band:
                direction = 1 if opening_move > 0 else -1
                bucket[str(band)].append({
                    "continuation": direction * forward_return,
                    "reversal": -direction * forward_return,
                })
    return train, holdout


def _report(rows: list[dict]) -> dict[str, dict]:
    return {
        "continuation": _summary([row["continuation"] for row in rows]),
        "reversal": _summary([row["reversal"] for row in rows]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="TICKER=CSV",
                        help="Repeat for each frozen 5-minute CSV, e.g. TSLA=data/TSLA_5m.csv")
    parser.add_argument("--split", required=True, help="ISO timestamp; later entries form untouched holdout")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    parsed: list[tuple[str, Path]] = []
    for item in args.input:
        if "=" not in item:
            parser.error("--input must be TICKER=CSV")
        ticker, raw_path = item.split("=", 1)
        if not ticker.strip() or not raw_path.strip():
            parser.error("--input must be TICKER=CSV")
        parsed.append((ticker.upper().strip(), Path(raw_path)))

    per_symbol: dict[str, dict] = {}
    pooled_train: dict[str, list[dict]] = {str(band): [] for band in MOVE_BANDS}
    pooled_holdout: dict[str, list[dict]] = {str(band): [] for band in MOVE_BANDS}
    for ticker, path in parsed:
        train, holdout = _observations(path, split)
        per_symbol[ticker] = {
            "path": str(path), "train": {band: _report(rows) for band, rows in train.items()},
            "holdout": {band: _report(rows) for band, rows in holdout.items()},
        }
        for band in pooled_train:
            pooled_train[band].extend(train[band])
            pooled_holdout[band].extend(holdout[band])
    payload = {
        "purpose": "Opening-drive market study only; no strategy, option quote, or trading action.",
        "fixed_design": {
            "opening_window": "09:30-10:00 ET", "entry_reference": "10:00 open",
            "exit_reference": "11:30 open", "opening_move_bands": [round(band * 100, 2) for band in MOVE_BANDS],
        },
        "split": split.isoformat(), "symbols": per_symbol,
        "pooled": {
            "train": {band: _report(rows) for band, rows in pooled_train.items()},
            "holdout": {band: _report(rows) for band, rows in pooled_holdout.items()},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
