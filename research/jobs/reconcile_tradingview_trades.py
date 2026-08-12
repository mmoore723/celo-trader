"""Compare exported TradingView trades with a V2 immutable trade ledger."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.ledger import load_trade_ledger
from research.engine.reconciliation import load_tradingview_trades, reconcile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tradingview-csv", required=True)
    parser.add_argument("--v2-ledger", required=True)
    parser.add_argument("--timezone", default="America/New_York")
    args = parser.parse_args()
    result = reconcile(load_tradingview_trades(args.tradingview_csv, args.timezone),
                       load_trade_ledger(args.v2_ledger))
    print(json.dumps({**asdict(result), "match_rate": result.match_rate}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
