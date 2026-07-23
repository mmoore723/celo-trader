"""
ab_test_stage1_dynamic.py — A/B tests the new dynamic stage1 profit-lock
trigger against the old flat-% behavior.

WHY THIS ONE: ab_test_stage1_target.py showed the flat % itself (50/30/20%)
wasn't the lever — ALL THREE were negative expectancy with ~0 winning
trades ever reaching the static target. Per that result and the follow-up
research (10+ sources, CLAUDE.md rule 9), the fix built into risk.py/
position_manager.py/backtest_exit_sim.py today replaces the single fixed %
with a per-trade trigger: ATR-scaled target (primary), momentum fade
(RSI exhaustion / MACD rollover), or volume fade (RVOL collapse) — each
gated by a minimum gain floor, falling back to the flat % only when ATR
data is missing.

TOGGLE: risk.py's RiskManager.STAGE1_DYNAMIC_ENABLED is the kill-switch —
False makes should_exit() behave exactly like the pre-2026-07-21 flat-%
logic (same code path used by every earlier A/B test this session).
Monkeypatching backtest_exit_sim._risk.STAGE1_DYNAMIC_ENABLED (the actual
runtime instance, same reasoning as ab_test_stage1_target.py) toggles it
for this comparison only.

HONEST LIMITATION: same yfinance ~60-day intraday cap, same single
overlapping backtest window as every other test this session — no
walk-forward validation. A win here means "worth paper trading," not
"proven." See module docstrings in risk.py/stage1 comment block and
ab_test_stage1_target.py for the full research trail.

Usage:
    python3 ab_test_stage1_dynamic.py                     # 2mo, default tickers
    python3 ab_test_stage1_dynamic.py 2 SPY QQQ NVDA AAPL TSLA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
import backtest_exit_sim
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]
DEFAULT_MONTHS  = 2


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

    _orig = backtest_exit_sim._risk.STAGE1_DYNAMIC_ENABLED
    results = {}
    try:
        for enabled in (True, False):
            label = "DYNAMIC (new)" if enabled else "FLAT % (old, corrected 50% baseline)"
            print(f"\n=== STAGE1 DYNAMIC = {enabled} — {label} ===")
            backtest_exit_sim._risk.STAGE1_DYNAMIC_ENABLED = enabled
            results[enabled] = _run_variant(alpaca, tickers, months)
    finally:
        # Always restore — this script must never leave live behavior changed.
        backtest_exit_sim._risk.STAGE1_DYNAMIC_ENABLED = _orig

    print("\n" + "=" * 82)
    print("DYNAMIC vs FLAT STAGE1 TRIGGER — A/B RESULT")
    print("=" * 82)
    for enabled, d in results.items():
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        tag = " (current default)" if enabled == _orig else ""
        print(f"dynamic={enabled}{tag:<20} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")
        _top_reasons = sorted(d["exit_reasons"].items(), key=lambda kv: -kv[1])[:5]
        print(f"    top exit reasons: {_top_reasons}")

    print("\nRead this as a DIRECTION, not a verdict — same single overlapping")
    print("backtest window as every other test this session (yfinance's ~60-day")
    print("intraday cap). A better number here means the next step is paper")
    print("trading it for real weeks, not re-running this script and calling it proof.")
    print("\nLive risk.py is unchanged by this script (STAGE1_DYNAMIC_ENABLED restored).")


if __name__ == "__main__":
    main()
