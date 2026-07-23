"""
ab_test_structural_stop_mode.py — A/B/C/D test for MID_BRK/TREND_CONT's
structural stop reference level.

WHY THIS EXISTS (2026-07-22): the mid_brk/trend_cont audit found neither
strategy ever supplied a structural stop (entry_bar_high/low), so both fell
back to the wider, lag-prone ATR stop from tick one — even though both are
"confirmation entries" that research says should be paired with a TIGHT
stop just beyond the pivot that confirmed the setup. Both strategy files
now support a STRUCT_STOP_MODE toggle:
    "none"        — no structural stop (the pre-2026-07-21 control)
    "entry_bar"   — this bar's own high/low (tightest, mirrors INST_ORB)
    "pivot"       — the LH/HL price that confirmed the entry (current default)
    "prior_swing" — the swing BEFORE that pivot (wider, more conservative)

This script monkeypatches both strategy modules' STRUCT_STOP_MODE together
per variant (both got the same fix, same reasoning) and reports results
both combined and split per strategy, so a win/loss in one doesn't hide in
the combined number. Same monkeypatch-restore-in-finally pattern as every
other ab_test_*.py this session.

CAVEAT: SPY/QQQ, ~2 months, single overlapping window — directional
evidence, not proof.

Usage:
    python3 ab_test_structural_stop_mode.py [months] [TICKER TICKER ...]
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict

from broker import AlpacaClient
from backtester import Backtester
import strategies.mid_brk as _mid_brk
import strategies.trend_cont as _trend_cont

DEFAULT_TICKERS = ["SPY", "QQQ"]
DEFAULT_MONTHS  = 2

_VARIANTS = [
    ("A: none (control — pre-2026-07-21 behavior, ATR stop only)", "none"),
    ("B: entry_bar (tightest — this bar's own high/low)",           "entry_bar"),
    ("C: pivot (current default — the LH/HL that confirmed entry)", "pivot"),
    ("D: prior_swing (widest — the swing before the pivot)",        "prior_swing"),
]


def _run_variant(alpaca, tickers: list[str], months: int, mode: str) -> dict:
    _mid_brk.STRUCT_STOP_MODE     = mode
    _trend_cont.STRUCT_STOP_MODE  = mode

    all_trades: list[dict] = []
    for ticker in tickers:
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
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
        return {
            "trades":     len(pnls),
            "win_rate":   (len(wins) / len(pnls) * 100) if pnls else 0.0,
            "total_pnl":  sum(pnls),
            "expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
        }

    mid_brk_trades   = [t for t in all_trades if t.get("strategy_id") == "MID_BRK"]
    trend_cont_trades = [t for t in all_trades if t.get("strategy_id") == "TREND_CONT"]

    return {
        "combined":   _stats(all_trades),
        "MID_BRK":    _stats(mid_brk_trades),
        "TREND_CONT": _stats(trend_cont_trades),
    }


def _fmt_row(label: str, s: dict) -> str:
    return (f"  {label:<12} {s['trades']:>7} {s['win_rate']:>5.0f}% "
            f"{s['expectancy']:>+10.2f}$ {s['total_pnl']:>+10.2f}$")


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_MONTHS
    tickers = [a.upper() for a in sys.argv[2:]] or DEFAULT_TICKERS
    if len(sys.argv) > 1 and not sys.argv[1].isdigit():
        tickers = [a.upper() for a in sys.argv[1:]]

    alpaca = AlpacaClient()
    print(f"STRUCTURAL STOP MODE A/B TEST — {months} month(s), tickers: {', '.join(tickers)}\n")

    _orig_mb_mode = _mid_brk.STRUCT_STOP_MODE
    _orig_tc_mode = _trend_cont.STRUCT_STOP_MODE

    results = []
    try:
        for label, mode in _VARIANTS:
            t0 = time.monotonic()
            print(f"⏳ {label}…", flush=True)
            r = _run_variant(alpaca, tickers, months, mode)
            r["label"] = label
            results.append(r)
            c = r["combined"]
            print(f"   done ({time.monotonic() - t0:.0f}s) — {c['trades']} trades combined, "
                  f"WR {c['win_rate']:.0f}%, expectancy ${c['expectancy']:+.2f}", flush=True)
    finally:
        _mid_brk.STRUCT_STOP_MODE    = _orig_mb_mode
        _trend_cont.STRUCT_STOP_MODE = _orig_tc_mode

    print("\n" + "=" * 100)
    print("RESULT")
    print("=" * 100)
    print(f"{'VARIANT':<12} {'TRADES':>7} {'WIN%':>6} {'EXPECTANCY':>11} {'TOTAL P&L':>11}")
    for r in results:
        print(f"\n{r['label']}")
        print(_fmt_row("combined", r["combined"]))
        print(_fmt_row("MID_BRK", r["MID_BRK"]))
        print(_fmt_row("TREND_CONT", r["TREND_CONT"]))

    print("\nReading this: if C (pivot, the tight research-backed stop) beats A (none/ATR-only)\n"
          "on both strategies, that confirms the fix. If B (entry_bar) beats C, the pivot is\n"
          "still too wide and the tightest possible stop is better. If D (prior_swing) beats C,\n"
          "the pivot itself is too tight and getting whipsawed on normal noise. Small\n"
          "overlapping sample (SPY/QQQ only) — directional, not proof.")


if __name__ == "__main__":
    main()
