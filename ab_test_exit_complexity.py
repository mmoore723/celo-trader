"""
ab_test_exit_complexity.py — A/B test: current 9+-condition exit stack vs.
the stripped-down 3-rule exit (backtest_exit_sim_simplified.py).

WHY THIS EXISTS (2026-07-22): published overfitting research names 8-10
tunable variables as the danger zone for a trading strategy, and today's
own STRUCT_STOP_MODE A/B test showed exactly that fragility (4 variants,
4 different outcomes, all negative, from changing ONE input). The current
exit engine has nine-plus separately-named exit paths. This tests the
opposite hypothesis: does REMOVING complexity down to 3 rules (hard stop,
a single 3.0x ATR chandelier trail, one time cap) — rather than tuning a
10th knob — produce a more robust, better result?

Uses Backtester.SIMPLIFIED_EXIT_MODE (see backtester.py) to toggle between
the two engines per variant. No entry-side changes at all — this isolates
the exit logic specifically, since today's research concluded the entries
are not the primary suspect.

CAVEAT (same as every ab_test_*.py this session): SPY/QQQ, ~2 months,
single overlapping backtest window — directional evidence, not proof.

Usage:
    python3 ab_test_exit_complexity.py [months] [TICKER TICKER ...]
    python3 ab_test_exit_complexity.py 2 SPY QQQ
"""

from __future__ import annotations

import sys
import time

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ"]
DEFAULT_MONTHS  = 2

_VARIANTS = [
    ("A: current stack (9+ conditions, control)", False),
    ("B: simplified (hard stop / 3.0x chandelier / 1 time cap)", True),
]


def _run_variant(alpaca, tickers: list[str], months: int, simplified: bool) -> dict:
    all_trades: list[dict] = []
    for ticker in tickers:
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.SIMPLIFIED_EXIT_MODE = simplified
        result = bt.run()
        if result.get("error"):
            continue
        for t in result.get("trades", []):
            t = dict(t)
            t["ticker"] = ticker
            all_trades.append(t)

    def _stats(trades: list[dict]) -> dict:
        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        return {
            "trades":      len(pnls),
            "win_rate":    (len(wins) / len(pnls) * 100) if pnls else 0.0,
            "total_pnl":   sum(pnls),
            "expectancy":  (sum(pnls) / len(pnls)) if pnls else 0.0,
            "avg_win":     (sum(wins) / len(wins)) if wins else 0.0,
            "avg_loss":    (sum(losses) / len(losses)) if losses else 0.0,
        }

    by_strategy: dict[str, list[dict]] = {}
    for t in all_trades:
        by_strategy.setdefault(t.get("strategy_id", "UNKNOWN"), []).append(t)

    return {
        "combined": _stats(all_trades),
        "by_strategy": {sid: _stats(ts) for sid, ts in by_strategy.items()},
    }


def _fmt_row(label: str, s: dict) -> str:
    rr = (abs(s["avg_win"] / s["avg_loss"]) if s["avg_loss"] else 0.0)
    return (f"  {label:<12} {s['trades']:>7} {s['win_rate']:>5.0f}% "
            f"{s['expectancy']:>+10.2f}$ {s['total_pnl']:>+10.2f}$ "
            f"  avg_win={s['avg_win']:>+7.2f} avg_loss={s['avg_loss']:>+8.2f} realized_RR={rr:.2f}x")


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_MONTHS
    tickers = [a.upper() for a in sys.argv[2:]] or DEFAULT_TICKERS
    if len(sys.argv) > 1 and not sys.argv[1].isdigit():
        tickers = [a.upper() for a in sys.argv[1:]]

    alpaca = AlpacaClient()
    print(f"EXIT COMPLEXITY A/B TEST — {months} month(s), tickers: {', '.join(tickers)}\n")

    results = []
    for label, simplified in _VARIANTS:
        t0 = time.monotonic()
        print(f"⏳ {label}…", flush=True)
        r = _run_variant(alpaca, tickers, months, simplified)
        r["label"] = label
        results.append(r)
        c = r["combined"]
        print(f"   done ({time.monotonic() - t0:.0f}s) — {c['trades']} trades combined, "
              f"WR {c['win_rate']:.0f}%, expectancy ${c['expectancy']:+.2f}", flush=True)

    print("\n" + "=" * 100)
    print("RESULT")
    print("=" * 100)
    for r in results:
        print(f"\n{r['label']}")
        print(_fmt_row("combined", r["combined"]))
        for sid, s in sorted(r["by_strategy"].items()):
            if s["trades"] >= 5:
                print(_fmt_row(sid, s))
            else:
                print(f"  {sid:<12} n={s['trades']} — below 5-trade floor, skipping (noise)")

    print("\nReading this: if B (simplified) beats A on realized R:R and expectancy, that supports\n"
          "the overfitting hypothesis — fewer, wider rules let winners actually run instead of\n"
          "getting nickel-and-dimed by 9 different ways to exit early. If A still wins, the extra\n"
          "conditions are pulling their weight and the complexity isn't the problem.\n"
          "Small overlapping sample (SPY/QQQ only) — directional, not proof.")


if __name__ == "__main__":
    main()
