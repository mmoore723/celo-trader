"""
audit_strategies.py — Per-strategy expectancy audit using the fixed logic.

Runs the backtester (which mirrors live entry/exit logic, including the
2026-07-15 fixes: two-session entry windows, momentum-dead -10% requirement,
5% slippage on fills) across the core tickers and prints a per-strategy
expectancy table.

Usage (on EC2, from the repo root):
    python3 audit_strategies.py            # 3 months, SPY QQQ NVDA
    python3 audit_strategies.py 6          # 6 months
    python3 audit_strategies.py 3 SPY QQQ  # custom ticker list

Read the table like this:
    expectancy = avg $ per trade AFTER slippage — positive = has an edge
    A strategy with negative expectancy over 30+ trades should be disabled.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS

    alpaca = AlpacaClient()

    # Aggregate per-strategy stats across all tickers
    agg: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    per_ticker_lines: list[str] = []

    for ticker in tickers:
        print(f"\n⏳ Backtesting {ticker} — {months} months (all strategies)…", flush=True)
        try:
            bt     = Backtester(alpaca, ticker, months=months,
                                starting_capital=5000.0, direction="both")
            result = bt.run()
        except Exception as ex:
            print(f"   ❌ {ticker} failed: {ex}")
            continue

        if result.get("error"):
            print(f"   ❌ {ticker}: {result['error']}")
            continue

        breakdown = result.get("strategy_breakdown") or {}
        per_ticker_lines.append(
            f"{ticker}: {result.get('total_trades', 0)} trades, "
            f"return {result.get('total_return_pct', 0):+.1f}%, "
            f"win rate {result.get('win_rate_pct', 0):.0f}%, "
            f"max DD {result.get('max_drawdown_pct', 0):.1f}%"
        )
        for sid, row in breakdown.items():
            agg[sid]["trades"] += int(row.get("trades", 0))
            agg[sid]["wins"]   += int(row.get("wins", 0))
            agg[sid]["pnl"]    += float(row.get("pnl", 0.0))

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print("PER-TICKER SUMMARY")
    print("=" * 68)
    for line in per_ticker_lines:
        print("  " + line)

    print("\n" + "=" * 68)
    print(f"{'STRATEGY':<12} {'TRADES':>7} {'WIN%':>6} {'TOTAL P&L':>11} "
          f"{'EXPECTANCY':>11}  VERDICT")
    print("=" * 68)

    # Sort by expectancy, best first
    def _expectancy(s: dict) -> float:
        return s["pnl"] / s["trades"] if s["trades"] else 0.0

    for sid, s in sorted(agg.items(), key=lambda kv: _expectancy(kv[1]), reverse=True):
        n   = s["trades"]
        wr  = (s["wins"] / n * 100) if n else 0.0
        exp = _expectancy(s)
        if n < 10:
            verdict = "⚪ too few trades to judge"
        elif exp > 5:
            verdict = "🟢 keep enabled"
        elif exp > 0:
            verdict = "🟡 marginal — watch"
        else:
            verdict = "🔴 DISABLE — negative expectancy"
        print(f"{sid:<12} {n:>7} {wr:>5.0f}% {s['pnl']:>+10.2f}$ "
              f"{exp:>+10.2f}$  {verdict}")

    print("\nNote: results include 5% slippage per side and the new entry windows.")
    print("Disable 🔴 strategies in Settings → Strategies, then re-run to confirm.")


if __name__ == "__main__":
    main()
