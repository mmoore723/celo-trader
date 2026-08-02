"""
ab_test_mid_brk_consolidation.py — A/B test MID_BRK's reference level: the
mechanical 15-min opening range vs. a wider 45-min morning consolidation
range.

Triggered by an independent chart read of SPY on 2026-07-16: price spent
~45 minutes consolidating around 753.5-753.9 before the real breakdown, but
the 15-min OR low (751.13) sat well below that and wasn't touched until
after MID_BRK's 10:30-13:00 session window had already closed — meaning
MID_BRK structurally couldn't catch the move a chart-reader would have
taken. This tests whether referencing the wider consolidation range instead
fixes that, the same way every other change here gets tested: built OFF by
default, flipped, compared, restored regardless of outcome.

Usage:
    python3 ab_test_mid_brk_consolidation.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_mid_brk_consolidation.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
from backtester import Backtester
import strategies.mid_brk as mid_brk

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        # See session-window harness: force this frozen strategy on only in
        # the isolated replay so an A/B never degrades into a false 0-trade
        # result because of the production safety setting.
        bt.enabled_strategies = set(bt.enabled_strategies) | {"MID_BRK"}
        result = bt.run()
        row    = (result.get("strategy_breakdown") or {}).get("MID_BRK", {})
        trades += int(row.get("trades", 0))
        wins   += int(row.get("wins", 0))
        pnl    += float(row.get("pnl", 0.0))
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig = mid_brk.CONSOLIDATION_RANGE_ENABLED
    try:
        print("\n=== VARIANT A: 15-min opening range (current live default) ===")
        mid_brk.CONSOLIDATION_RANGE_ENABLED = False
        old_result = _run_variant(alpaca, tickers, months, "15min-OR")

        print("\n=== VARIANT B: 45-min morning consolidation range ===")
        mid_brk.CONSOLIDATION_RANGE_ENABLED = True
        new_result = _run_variant(alpaca, tickers, months, "45min-consol")
    finally:
        # Always restore — this script must never leave live behavior changed
        mid_brk.CONSOLIDATION_RANGE_ENABLED = _orig

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<20} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 74)
    print("MID_BRK CONSOLIDATION-RANGE A/B RESULT")
    print("=" * 74)
    _report("15-MIN OR (old)", old_result)
    _report("45-MIN CONSOL (new)", new_result)

    print("\nVerdict:")
    if new_result["trades"] < 5:
        print("  ⚪ Too few trades in the new variant to trust — do not ship yet.")
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
