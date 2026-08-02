"""Fetch one V2 research artifact from the authenticated Alpaca data feed."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.providers import export_alpaca_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--start", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="exclusive YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    # Deliberately lazy: documentation/help must not require broker runtime
    # dependencies, while an actual authenticated export does.
    from broker import get_clients
    alpaca, _ = get_clients()
    path = export_alpaca_csv(
        alpaca, args.symbol, date.fromisoformat(args.start), date.fromisoformat(args.end),
        args.output, limit=args.limit,
    )
    dataset = load_csv(path)
    print(f"saved {len(dataset.bars)} bars to {path}; sha256={dataset.sha256}")


if __name__ == "__main__":
    main()
