"""
ab_test_trend_cont_maxbars.py — A/B test tightening TREND_CONT's pivot
staleness cutoff (_MAX_BARS).

diag_trend_cont_features.py found a real, clean gap between winning and
losing TREND_CONT trades: winners re-enter on a fresh LH/HL pivot
(avg 4 bars ago), losers re-enter on a much staler one (avg 9 bars ago).
_MAX_BARS currently allows pivots up to 20 bars (100 min) old — this tests
whether tightening that to 10 bars (50 min) improves expectancy, the same
way every other change in this codebase gets tested: build disabled/at the
old value, flip it, compare, restore regardless of outcome.

Usage:
    python3 ab_test_trend_cont_maxbars.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_trend_cont_maxbars.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
from backtester import Backtester
import strategies.trend_cont as trend_cont

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        row    = (result.get("strategy_breakdown") or {}).get("TREND_CONT", {})
        trades += int(row.get("trades", 0))
        wins   += int(row.get("wins", 0))
        pnl    += float(row.get("pnl", 0.0))
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig = trend_cont._MAX_BARS
    try:
        print(f"\n=== VARIANT A: _MAX_BARS = {_orig} (current live default) ===")
        trend_cont._MAX_BARS = _orig
        old_result = _run_variant(alpaca, tickers, months, "bars=20")

        print("\n=== VARIANT B: _MAX_BARS = 10 (fresh-pivot-only) ===")
        trend_cont._MAX_BARS = 10
        new_result = _run_variant(alpaca, tickers, months, "bars=10")
    finally:
        # Always restore — this script must never leave live behavior changed
        trend_cont._MAX_BARS = _orig

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<18} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 72)
    print("TREND_CONT _MAX_BARS A/B RESULT")
    print("=" * 72)
    _report("BARS=20 (old)", old_result)
    _report("BARS=10 (new)", new_result)

    print("\nVerdict:")
    if new_result["trades"] < 5:
        print("  ⚪ Too few trades in the tightened variant to trust — do not ship yet.")
    else:
        old_exp = (old_result["pnl"] / old_result["trades"]) if old_result["trades"] else 0.0
        new_exp = (new_result["pnl"] / new_result["trades"]) if new_result["trades"] else 0.0
        if new_exp > old_exp and new_exp > 0:
            print(f"  🟢 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) and positive — ship it.")
        elif new_exp > old_exp:
            print(f"  🟡 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) but still negative — do not ship.")
        else:
            print(f"  🔴 No improvement (${old_exp:+.2f} -> ${new_exp:+.2f}/trade). Do not ship.")

    print("\nLive bot behavior is unchanged by this script (flag restored).")


if __name__ == "__main__":
    main()
