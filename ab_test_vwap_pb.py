"""
ab_test_vwap_pb.py — A/B test for the proposed VWAP_PB blowthrough loosening.

Background
──────────
The 2026-07-15 audit found VWAP_PB losing -$135 to -$148 per trade with a
3-of-5-bars blowthrough guard (10% win rate). Tightening to 5-of-5 (require
ALL 5 recent bars on the correct side of VWAP) cut the damage to -$495 total
over 5 trades — still negative, but an 89% improvement.

A proposal came in to loosen back to 3-of-5 (sum(...) >= 3) plus a
"fast_recovery" exception that allows entry when price pierces below/above
VWAP and then reclaims instantly with a strong-bodied candle. That pattern is
hard to distinguish from the blowthrough crashes the guard was built to stop,
so it is NOT enabled in the live bot. This script tests it in isolation
before any live change is considered.

This script does NOT touch live behavior — it monkeypatches the module
constants in strategies.vwap_pb for the duration of the test only, and
restores them afterward.

Usage:
    python3 ab_test_vwap_pb.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_vwap_pb.py 6          # 6 months
    python3 ab_test_vwap_pb.py 6 SPY QQQ NVDA IWM
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
from backtester import Backtester
import strategies.vwap_pb as vwap_pb

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    """Run the full backtest and pull out just the VWAP_PB row per ticker."""
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months,
                            starting_capital=5000.0, direction="both")
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

    # Save originals so live behavior is restored no matter what happens
    _orig_min_bars = vwap_pb.BLOWTHROUGH_MIN_BARS
    _orig_fast_rec = vwap_pb.FAST_RECOVERY_ENABLED

    try:
        print("\n=== VARIANT A: current live default (5-of-5, no fast recovery) ===")
        vwap_pb.BLOWTHROUGH_MIN_BARS  = 5
        vwap_pb.FAST_RECOVERY_ENABLED = False
        strict = _run_variant(alpaca, tickers, months, "strict")

        print("\n=== VARIANT B: proposed loosening (3-of-5 + fast recovery) ===")
        vwap_pb.BLOWTHROUGH_MIN_BARS  = 3
        vwap_pb.FAST_RECOVERY_ENABLED = True
        loose = _run_variant(alpaca, tickers, months, "loosened")

    finally:
        # Always restore — this script must never leave live behavior changed
        vwap_pb.BLOWTHROUGH_MIN_BARS  = _orig_min_bars
        vwap_pb.FAST_RECOVERY_ENABLED = _orig_fast_rec

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<10} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 68)
    print("VWAP_PB A/B RESULT")
    print("=" * 68)
    _report("STRICT", strict)
    _report("LOOSENED", loose)

    print("\nVerdict:")
    if loose["trades"] < 10:
        print("  ⚪ Loosened variant still has too few trades to trust — do not ship.")
    elif (loose["pnl"] / loose["trades"] if loose["trades"] else 0) > (
          strict["pnl"] / strict["trades"] if strict["trades"] else -999):
        print("  🟡 Loosened variant scored better on this sample. Still recommend")
        print("     a second time window / ticker set before flipping live defaults —")
        print("     one sample matching a hypothesis is not the same as confirming it.")
    else:
        print("  🔴 Loosened variant did NOT outperform. Keep the 5-of-5 strict guard.")
    print("\nLive bot behavior is unchanged by this script (constants restored).")


if __name__ == "__main__":
    main()
