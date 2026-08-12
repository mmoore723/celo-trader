#!/usr/bin/env python3
"""Create a deterministic regular-session OHLCV aggregation for research."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv, resample_regular_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-minutes", required=True, type=int)
    parser.add_argument("--target-minutes", required=True, type=int)
    args = parser.parse_args()

    dataset = load_csv(args.input)
    bars = resample_regular_session(
        dataset.bars, source_minutes=args.source_minutes, target_minutes=args.target_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
        writer.writerows((
            (bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in bars
        ))
    print(f"wrote {len(bars)} bars to {args.output}")


if __name__ == "__main__":
    main()
