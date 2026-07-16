"""
diag_aft_rev.py — Trade-by-trade AFT_REV diagnostic.

The strategy table said AFT_REV lost every trade it took (0% WR across two
audit runs), but that's a different problem than "the session gate is
starving it of entries" — the gate isn't the issue if trades ARE firing.
This prints each individual AFT_REV trade (direction, entry hour, exit
reason, P&L, held minutes) so we diagnose from the actual losing trades
instead of guessing at the gate.

Usage:
    python3 diag_aft_rev.py            # 3 months, SPY QQQ NVDA
    python3 diag_aft_rev.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    all_trades = []
    for ticker in tickers:
        print(f"⏳ {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.run()
        for t in bt.trades:
            if t.get("strategy_id") == "AFT_REV":
                t = dict(t)
                t["ticker"] = ticker
                all_trades.append(t)

    print("\n" + "=" * 90)
    print(f"AFT_REV — {len(all_trades)} trade(s) found")
    print("=" * 90)
    if not all_trades:
        print("No AFT_REV trades fired at all in this window — THIS would confirm a gate problem.")
        return

    print(f"{'DATE':<11} {'TICKER':<6} {'DIR':<6} {'HOUR':>4} {'HELD(m)':>8} "
          f"{'ENTRY':>7} {'EXIT':>7} {'P&L':>9}  EXIT REASON")
    print("-" * 90)
    for t in sorted(all_trades, key=lambda x: (x.get("date", ""), x.get("entry_hour", 0))):
        print(f"{t.get('date',''):<11} {t.get('ticker',''):<6} {t.get('direction',''):<6} "
              f"{t.get('entry_hour',0):>4} {t.get('held_minutes',0):>8.1f} "
              f"{t.get('entry_price',0):>7.2f} {t.get('exit_price',0):>7.2f} "
              f"{t.get('pnl',0):>+9.2f}  {t.get('exit_reason','')}")

    reasons = {}
    for t in all_trades:
        r = t.get("exit_reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1
    print("\nExit reason breakdown:")
    for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {r:<28} {n}")

    hours = {}
    for t in all_trades:
        h = t.get("entry_hour", 0)
        hours[h] = hours.get(h, 0) + 1
    print("\nEntry hour distribution (13-15 expected given the 13:00-15:30 gate):")
    for h in sorted(hours):
        print(f"  {h}:00  —  {hours[h]} trade(s)")


if __name__ == "__main__":
    main()
