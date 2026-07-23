"""
ab_test_momentum_fade_tuning.py — A/B/C/D tests the momentum-fade trigger's
minimum floor and OR-vs-AND logic.

WHY THIS ONE: ab_test_stage1_dynamic.py's exit-mix breakdown (after fixing
the mislabeling bug in backtester.py) showed ALL stage1 exits firing via
momentum_fade — zero via the ATR target, volume fade, or static fallback.
At only +10% gain required, either RSI exhaustion OR MACD fade alone was
enough to trigger, never giving the 2x-ATR target room to work. Testing
two candidate fixes, isolated AND combined, rather than assuming the
combined change is what helped (same "change one variable at a time"
discipline as every other test this session):

  A. floor=10%, OR   — current live default (baseline)
  B. floor=25%, OR   — floor-only change
  C. floor=10%, AND  — logic-only change
  D. floor=25%, AND  — both changes combined

HONEST LIMITATION: same yfinance ~60-day intraday cap, same single
overlapping backtest window as every other test this session. A win here
means "worth paper trading," not "proven."

Usage:
    python3 ab_test_momentum_fade_tuning.py                     # 2mo, default tickers
    python3 ab_test_momentum_fade_tuning.py 2 SPY QQQ NVDA AAPL TSLA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
import backtest_exit_sim
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]
DEFAULT_MONTHS  = 2

# (floor_pct, require_both, label)
_VARIANTS = [
    (0.10, False, "A: floor=10% OR (current default)"),
    (0.25, False, "B: floor=25% OR (floor-only)"),
    (0.10, True,  "C: floor=10% AND (logic-only)"),
    (0.25, True,  "D: floor=25% AND (combined — friend's proposal)"),
]


def _run_variant(alpaca, tickers, months) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    exit_reasons: dict[str, int] = {}
    for ticker in tickers:
        print(f"  ⏳ {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        if result.get("error"):
            print(f"     ❌ {ticker}: {result['error']}")
            continue
        trades += result.get("total_trades", 0)
        wins   += int(result.get("total_trades", 0) * result.get("win_rate", 0))
        pnl    += result.get("total_pnl", 0.0)
        for row in result.get("trades", []) or []:
            _reason = str(row.get("exit_reason", "unknown")).split(" ")[0]
            exit_reasons[_reason] = exit_reasons.get(_reason, 0) + 1
    return {"trades": trades, "wins": wins, "pnl": pnl, "exit_reasons": exit_reasons}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig_floor = backtest_exit_sim._risk.STAGE1_MIN_LOCK_FLOOR_PCT
    _orig_both  = backtest_exit_sim._risk.STAGE1_MOMENTUM_REQUIRE_BOTH
    results = {}
    try:
        for floor, both, label in _VARIANTS:
            print(f"\n=== {label} ===")
            backtest_exit_sim._risk.STAGE1_MIN_LOCK_FLOOR_PCT  = floor
            backtest_exit_sim._risk.STAGE1_MOMENTUM_REQUIRE_BOTH = both
            results[label] = _run_variant(alpaca, tickers, months)
    finally:
        # Always restore — this script must never leave live behavior changed.
        backtest_exit_sim._risk.STAGE1_MIN_LOCK_FLOOR_PCT    = _orig_floor
        backtest_exit_sim._risk.STAGE1_MOMENTUM_REQUIRE_BOTH = _orig_both

    print("\n" + "=" * 88)
    print("MOMENTUM-FADE FLOOR/LOGIC TUNING — A/B/C/D RESULT")
    print("=" * 88)
    for label, d in results.items():
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{label:<48} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")
        _top_reasons = sorted(d["exit_reasons"].items(), key=lambda kv: -kv[1])[:5]
        print(f"    top exit reasons: {_top_reasons}")

    print("\nRead this as a DIRECTION, not a verdict — same single overlapping")
    print("backtest window as every other test this session (yfinance's ~60-day")
    print("intraday cap). A better number here means the next step is paper")
    print("trading it for real weeks, not re-running this script and calling it proof.")
    print("\nLive risk.py is unchanged by this script (both values restored).")


if __name__ == "__main__":
    main()
