"""
ab_test_confidence_floor.py — A/B/C tests strategy_router's confidence
floor (currently 0.74) at lower values.

Why this one and not another strategy-specific tweak: run_full_audit.py's
2026-07-21 funnel showed the confidence floor killing ~80% of all raw
signals (229 of 287 in the last run) — by far the single biggest filter in
the whole entry pipeline, dwarfing conflict veto (0) and every per-strategy
gate combined. If any one number is worth testing next, it's this one.

HONEST LIMITATION: yfinance's 5-minute-bar history caps at ~60 days, so
there's no way to walk-forward test this across independent, non-overlapping
windows the way a real validation should — every run here uses the same
backtest window we've already looked at repeatedly today. That's a real
overfitting risk (see the research cited in chat). Treat a positive result
here as "worth trying live in paper trading," not "proven" — the actual
out-of-sample test is real paper trades over the next couple of weeks
without re-tuning the moment they wobble.

Usage:
    python3 ab_test_confidence_floor.py                     # 2mo, default tickers
    python3 ab_test_confidence_floor.py 2 SPY QQQ NVDA AAPL TSLA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
import backtester
import strategy_router
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]
DEFAULT_MONTHS  = 2

# Current live value, plus two lower candidates informed by the 80% kill
# rate — not picked to hit a target, just spaced out to see the shape of
# the trade-off (more trades vs. win rate) before picking one.
_FLOOR_VARIANTS = [0.74, 0.68, 0.62]


def _run_variant(alpaca, tickers, months, floor: float) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ floor={floor}: {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        if result.get("error"):
            print(f"     ❌ {ticker}: {result['error']}")
            continue
        trades += result.get("total_trades", 0)
        wins   += int(result.get("total_trades", 0) * result.get("win_rate", 0))
        pnl    += result.get("total_pnl", 0.0)
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    # FIX 2026-07-28: route_signals() (called inside Backtester.run()) reads
    # the floor from strategy_router's own module-level _MIN_CONFIDENCE —
    # backtester.py only imports the route_signals FUNCTION, never the
    # constant, so patching backtester._MIN_CONFIDENCE was a no-op target
    # that didn't even exist there (AttributeError on first run). The floor
    # must be patched on strategy_router itself.
    _orig = strategy_router._MIN_CONFIDENCE
    results = {}
    try:
        for floor in _FLOOR_VARIANTS:
            print(f"\n=== FLOOR = {floor} {'(current live default)' if floor == _orig else ''} ===")
            strategy_router._MIN_CONFIDENCE = floor
            results[floor] = _run_variant(alpaca, tickers, months, floor)
    finally:
        # Always restore — this script must never leave live behavior changed.
        strategy_router._MIN_CONFIDENCE = _orig

    print("\n" + "=" * 78)
    print("CONFIDENCE FLOOR A/B/C RESULT")
    print("=" * 78)
    for floor, d in results.items():
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        tag = " (current)" if floor == _orig else ""
        print(f"floor={floor:<5}{tag:<10} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\nRead this as a DIRECTION, not a verdict — see the module docstring on")
    print("why a single repeated backtest window can't prove this. If a lower floor")
    print("looks better here, the real test is running it in paper trading for the")
    print("next couple of weeks and judging fresh trades, not re-running this script.")
    print("\nLive strategy_router.py is unchanged by this script (floor restored).")


if __name__ == "__main__":
    main()
