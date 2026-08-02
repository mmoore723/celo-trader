"""Compare the simplified and full exit engines on one locked holdout.

Entry routing is intentionally unchanged.  This isolates exit behaviour and
uses the exact requested historical window rather than a rough month count.
The script is read-only and never changes saved bot settings.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from broker import get_clients
from backtester import Backtester


DEFAULT_TICKERS = ("SPY", "QQQ", "NVDA", "AAPL", "META")
DEFAULT_START = "2026-07-15"
DEFAULT_END = "2026-08-01"


def _run(ticker: str, start: str, end: str, simplified: bool) -> dict[str, Any]:
    alpaca, _ = get_clients()
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    months = max(1, (end_date - start_date).days // 30 + 1)
    backtest = Backtester(
        alpaca, ticker, months=months, starting_capital=5000.0,
        direction="both", start_date=start_date, end_date=end_date,
    )
    backtest.SIMPLIFIED_EXIT_MODE = simplified
    result = backtest.run()
    if result.get("error"):
        return {"error": result["error"]}
    return {
        "return_pct": round(float(result["total_return"]), 3),
        "trades": int(result["total_trades"]),
        "pnl": round(float(result["total_pnl"]), 2),
        "final_balance": round(float(result["final_balance"]), 2),
        "expectancy": round(float(result["expectancy"]), 2),
        "avg_win": round(float(result["avg_win"]), 2),
        "avg_loss": round(float(result["avg_loss"]), 2),
        "exit_reasons": result["exit_reasons"],
    }


def compare_ticker(ticker: str, start: str, end: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "simplified": _run(ticker, start, end, simplified=True),
        "full": _run(ticker, start, end, simplified=False),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()
    # Validate dates once so a typo fails before consuming compute.
    date.fromisoformat(args.start); date.fromisoformat(args.end)

    panel = []
    for ticker in args.tickers:
        row = compare_ticker(ticker.upper(), args.start, args.end)
        panel.append(row)
        print(json.dumps(row), flush=True)
    print(json.dumps({"panel": panel}), flush=True)


if __name__ == "__main__":
    main()
