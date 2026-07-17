"""
ab_test_candlestick_filter.py — A/B test the VWAP_PB candlestick rejection filter.

Runs the full backtest twice per ticker — once with
strategies.vwap_pb.CANDLESTICK_FILTER_ENABLED off (current default) and once
with it on — and reports VWAP_PB's trades, win rate, and expectancy for both.

This is rule-based OHLC wick/body math (candlestick_patterns.py), NOT
machine learning — same discipline as every other change in this codebase:
built disabled, A/B tested before anything ships live. VWAP_PB itself stays
disabled in trading/entry.py._STRAT_DEFAULTS regardless of this result.

Usage:
    python3 ab_test_candlestick_filter.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_candlestick_filter.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
from backtester import Backtester
import strategies.vwap_pb as vwap_pb

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        row    = (result.get("strategy_breakdown") or {}).get("VWAP_PB", {})
        trades += int(row.get("trades", 0))
        wins   += int(row.get("wins", 0))
        pnl    += float(row.get("pnl", 0.0))
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig = vwap_pb.CANDLESTICK_FILTER_ENABLED
    try:
        print("\n=== VARIANT A: no candlestick filter (current live default) ===")
        vwap_pb.CANDLESTICK_FILTER_ENABLED = False
        off_result = _run_variant(alpaca, tickers, months, "no-filter")

        print("\n=== VARIANT B: candlestick rejection filter ON ===")
        vwap_pb.CANDLESTICK_FILTER_ENABLED = True
        on_result = _run_variant(alpaca, tickers, months, "filter-on")
    finally:
        # Always restore — this script must never leave live behavior changed
        vwap_pb.CANDLESTICK_FILTER_ENABLED = _orig

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<10} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 68)
    print("CANDLESTICK FILTER A/B RESULT (VWAP_PB only)")
    print("=" * 68)
    _report("NO FILTER", off_result)
    _report("FILTER ON", on_result)

    print("\nVerdict:")
    if on_result["trades"] < 10:
        print("  ⚪ Too few filtered trades to trust — do not ship, gather more data.")
    else:
        off_exp = (off_result["pnl"] / off_result["trades"]) if off_result["trades"] else 0.0
        on_exp  = (on_result["pnl"]  / on_result["trades"])  if on_result["trades"]  else 0.0
        if on_exp > off_exp and on_exp > 0:
            print(f"  🟡 Improved (${off_exp:+.2f} -> ${on_exp:+.2f}/trade) and positive — "
                  f"worth a second sample before flipping the live default.")
        elif on_exp > off_exp:
            print(f"  🟡 Improved (${off_exp:+.2f} -> ${on_exp:+.2f}/trade) but still negative — do not ship.")
        else:
            print(f"  🔴 No improvement (${off_exp:+.2f} -> ${on_exp:+.2f}/trade). Filter didn't help.")

    print("\nLive bot behavior is unchanged by this script (flag restored).")
    print("This is rule-based candlestick math, not ML — see candlestick_patterns.py.")


if __name__ == "__main__":
    main()
