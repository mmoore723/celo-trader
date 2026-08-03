#!/usr/bin/env python3
"""Run a strict real-quote ORB option markout diagnostic.

This is a research screen, not a trading command. It does not connect to a
broker and cannot place an order.

Example:
  python3 scripts/research_v2/run_orb_option_markouts.py \
    --ticker TSLA --bars research_data/TSLA_5m.csv \
    --quotes research_data/TSLA_option_quotes.csv --output reports/tsla_orb_markouts.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


# This script is deliberately runnable directly from the command line on the
# research server, not only as ``python -m`` from a configured shell.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.option_markouts import run_databento_cbbo_markouts, run_option_markouts
from research_v2.options import OptionQuoteBook, load_option_quotes
from research_v2.strategies import OpeningRangeBreakout, OpeningRangeBreakoutConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-quote ORB option markout diagnostic")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--bars", type=Path, required=True, help="Frozen regular-session underlying bars CSV")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--quotes", type=Path, help="Normalized option quotes CSV (memory-heavy; small files only)")
    source.add_argument("--cbbo-file", type=Path, help="Raw Databento .csv or .csv.zst file (streaming; preferred)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold-minutes", type=int, default=60)
    # Defaults mirror trading/entry/contract.py: 7–21 DTE, first OTM,
    # $0.80–$10 premium and the settings page's 8% spread cap. CBBO does not
    # include open interest, so that live filter is reported as unresolved.
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    args = parser.parse_args()

    bars = load_csv(args.bars).bars
    strategy = OpeningRangeBreakout(OpeningRangeBreakoutConfig())
    if args.cbbo_file:
        results = run_databento_cbbo_markouts(
            bars, [args.cbbo_file], strategy, underlying=args.ticker,
            hold_minutes=args.hold_minutes, min_dte=args.min_dte, max_dte=args.max_dte,
            min_premium=args.min_premium, max_premium=args.max_premium,
            max_spread_pct=args.max_spread_pct,
        )
        input_mode = "streaming_raw_cbbo"
    else:
        quotes = OptionQuoteBook(load_option_quotes(args.quotes))
        results = run_option_markouts(
            bars, quotes, strategy, underlying=args.ticker,
            hold_minutes=args.hold_minutes, max_dte=args.max_dte,
        )
        input_mode = "normalized_quote_csv"
    returns = [result.return_pct for result in results]
    summary = {
        "purpose": "Real bid/ask ORB markout diagnostic; not a live-exit or portfolio backtest.",
        "ticker": args.ticker.upper(), "input_mode": input_mode,
        "hold_minutes": args.hold_minutes, "min_dte": args.min_dte, "max_dte": args.max_dte,
        "min_premium": args.min_premium, "max_premium": args.max_premium,
        "max_spread_pct": args.max_spread_pct,
        "unresolved_live_filter": "Open interest is not present in CBBO; this diagnostic cannot verify the live OI >= 150 gate.",
        "measured_signals": len(results),
        "positive_markouts": sum(value > 0 for value in returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 1) if returns else None,
        "average_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "markouts": [
            {
                "signal_time": result.signal_time.isoformat(), "side": result.side.value,
                "contract": result.contract_symbol, "entry_ask": result.entry_ask,
                "exit_bid": result.exit_bid, "return_pct": result.return_pct,
            } for result in results
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "markouts"}, indent=2))


if __name__ == "__main__":
    main()
