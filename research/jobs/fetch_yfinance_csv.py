"""Fetch one explicit, reproducible V2 historical-bar artifact while online."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.providers import export_yfinance_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="exclusive YYYY-MM-DD")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = export_yfinance_csv(
        args.symbol, date.fromisoformat(args.start), date.fromisoformat(args.end),
        args.output, args.interval,
    )
    dataset = load_csv(path)
    print(f"saved {len(dataset.bars)} bars to {path}; sha256={dataset.sha256}")


if __name__ == "__main__":
    main()
