"""
ab_test_v2_fixes.py — A/B tests the 2026-07-21 entry-filter changes to
TREND_CONT and AFT_REV against their prior (live-until-today) behavior.

Both strategies were edited directly (not shipped behind a flag) based on
run_full_audit.py's win/loss feature-gap tables:
  TREND_CONT: _MAX_BARS 10 -> 6, added a min lh_depth_pct/hl_rise_pct floor.
  AFT_REV:    added a min BOS breakout-magnitude floor, capped the RVOL
              confidence bonus (losers ran hotter RVOL than winners).

Per project convention (see ab_test_mid_brk_adx_gate.py, ab_test_trend_cont_
maxbars.py): nothing gets treated as "fixed" until the real expectancy
number comes back better, not just the hypothesis. This script monkeypatches
the strategy modules back to their OLD (pre-07-21) constants for variant A,
runs the real backtester (now calling risk.py's actual exit engine — see
backtest_exit_sim.py) for variant B at today's shipped values, and restores
the live modules to their current (new) state regardless of outcome — the
strategy files are already at the NEW values; this script never changes
what's shipped, only what's tested in-memory.

Usage:
    python3 ab_test_v2_fixes.py                      # 2 months, SPY QQQ NVDA AAPL TSLA
    python3 ab_test_v2_fixes.py 3 SPY QQQ NVDA AAPL TSLA AMD META AMZN MSFT GOOGL
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
import strategies.trend_cont as trend_cont
import strategies.aft_rev as aft_rev
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]
DEFAULT_MONTHS  = 2

# Values live before the 2026-07-21 changes (see each module's docstring).
_OLD_TREND_CONT_MAX_BARS   = 10
_OLD_TREND_CONT_MIN_DEPTH  = -999.0   # effectively no floor — matches pre-fix behavior
_OLD_AFT_REV_MIN_BREAKOUT  = -999.0   # effectively no floor
_OLD_AFT_REV_RVOL_CAP      = 2.0


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    """Runs the full multi-strategy backtest per ticker, sums TREND_CONT + AFT_REV only."""
    out = {"TREND_CONT": {"trades": 0, "wins": 0, "pnl": 0.0},
           "AFT_REV":     {"trades": 0, "wins": 0, "pnl": 0.0}}
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        if result.get("error"):
            print(f"     ❌ {ticker}: {result['error']}")
            continue
        breakdown = result.get("strategy_breakdown") or {}
        for strat_id in ("TREND_CONT", "AFT_REV"):
            row = breakdown.get(strat_id, {})
            out[strat_id]["trades"] += int(row.get("trades", 0))
            out[strat_id]["wins"]   += int(row.get("wins", 0))
            out[strat_id]["pnl"]    += float(row.get("pnl", 0.0))
    return out


def _report(strat_id: str, name: str, d: dict) -> None:
    n   = d["trades"]
    wr  = (d["wins"] / n * 100) if n else 0.0
    exp = (d["pnl"] / n) if n else 0.0
    print(f"  {strat_id:<11} {name:<28} trades={n:>4}  win%={wr:>5.1f}%  "
          f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _new_tc_max_bars  = trend_cont._MAX_BARS
    _new_tc_min_depth = trend_cont._MIN_DEPTH_PCT
    _new_ar_min_bo    = aft_rev._MIN_BREAKOUT_PCT
    _new_ar_rvol_cap  = aft_rev._RVOL_BONUS_CAP

    try:
        print("\n=== VARIANT A: pre-07-21 behavior (old constants) ===")
        trend_cont._MAX_BARS      = _OLD_TREND_CONT_MAX_BARS
        trend_cont._MIN_DEPTH_PCT = _OLD_TREND_CONT_MIN_DEPTH
        aft_rev._MIN_BREAKOUT_PCT = _OLD_AFT_REV_MIN_BREAKOUT
        aft_rev._RVOL_BONUS_CAP   = _OLD_AFT_REV_RVOL_CAP
        old_result = _run_variant(alpaca, tickers, months, "old")

        print("\n=== VARIANT B: 2026-07-21 fix (current shipped constants) ===")
        trend_cont._MAX_BARS      = _new_tc_max_bars
        trend_cont._MIN_DEPTH_PCT = _new_tc_min_depth
        aft_rev._MIN_BREAKOUT_PCT = _new_ar_min_bo
        aft_rev._RVOL_BONUS_CAP   = _new_ar_rvol_cap
        new_result = _run_variant(alpaca, tickers, months, "new")
    finally:
        # Always restore to the currently-shipped values — this script must
        # never leave the modules in the OLD (variant A) state.
        trend_cont._MAX_BARS      = _new_tc_max_bars
        trend_cont._MIN_DEPTH_PCT = _new_tc_min_depth
        aft_rev._MIN_BREAKOUT_PCT = _new_ar_min_bo
        aft_rev._RVOL_BONUS_CAP   = _new_ar_rvol_cap

    print("\n" + "=" * 78)
    print("2026-07-21 ENTRY-FILTER FIX — A/B RESULT")
    print("=" * 78)
    for strat_id in ("TREND_CONT", "AFT_REV"):
        _report(strat_id, "OLD (pre-fix)", old_result[strat_id])
        _report(strat_id, "NEW (shipped today)", new_result[strat_id])
        old_n, new_n = old_result[strat_id]["trades"], new_result[strat_id]["trades"]
        old_exp = (old_result[strat_id]["pnl"] / old_n) if old_n else 0.0
        new_exp = (new_result[strat_id]["pnl"] / new_n) if new_n else 0.0
        print(f"  Verdict ({strat_id}):", end=" ")
        if new_n < 5:
            print("⚪ too few trades in the new variant to trust — treat as unproven.")
        elif new_exp > old_exp and new_exp > 0:
            print(f"🟢 improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) and positive — keep shipped.")
        elif new_exp > old_exp:
            print(f"🟡 improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) but still negative — revisit, don't declare fixed.")
        else:
            print(f"🔴 no improvement (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) — consider reverting this change.")
        print()

    print("Live strategy files are unchanged by this script (already at the NEW values tested above).")


if __name__ == "__main__":
    main()
