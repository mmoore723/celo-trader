"""
ab_test_mid_brk_rvol_ceiling.py — A/B/C/D test for an RVOL ceiling on MID_BRK.

WHY THIS EXISTS (2026-07-22): MID_BRK's bucketed trade data shows an inverse
RVOL/win-rate relationship (44% WR at RVOL<1.5 vs 9% at RVOL>3.0) — the
opposite of what a "volume confirmation" gate should produce. Gate 6's
existing floor (0.75x once MSA confirms) rarely binds, so it isn't causing
this; the pattern is naturally occurring in the data. Published sources give
a real mechanism: MID_BRK's RVOL check fires at LH-confirmation, AFTER the
initial breakdown bar — and post-breakout volume spikes more often signal
exhaustion/climactic selling than fresh continuation conviction. A ceiling
(reject entries where RVOL is too high) tests that mechanism directly.

This script monkeypatches strategies/mid_brk.RVOL_CEILING per variant and
restores it in finally — same pattern as every other ab_test_*.py this
session. Live behavior is unaffected unless someone edits the constant
directly in mid_brk.py.

Usage:
    python3 ab_test_mid_brk_rvol_ceiling.py [months] [TICKER TICKER ...]
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/
import time

from broker import AlpacaClient
from backtester import Backtester
import strategies.mid_brk as _mid_brk

DEFAULT_TICKERS = ["SPY", "QQQ"]
DEFAULT_MONTHS  = 2

_VARIANTS = [
    ("A: current 2.0x ceiling (control)",   2.0),
    ("B: tighter 1.5x ceiling",              1.5),
    ("C: looser 2.5x ceiling (sensitivity)", 2.5),
    ("D: no ceiling (sensitivity)",          None),
]


def _run_variant(alpaca, tickers: list[str], months: int, ceiling) -> dict:
    _mid_brk.RVOL_CEILING = ceiling

    all_trades: list[dict] = []
    for ticker in tickers:
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        # MID_BRK is intentionally disabled in paper/live settings.  Enable
        # it only in this throwaway Backtester instance for hypothetical A/B.
        bt.enabled_strategies = set(bt.enabled_strategies) | {"MID_BRK"}
        result = bt.run()
        if result.get("error"):
            continue
        for t in result.get("trades", []):
            t = dict(t)
            t["ticker"] = ticker
            all_trades.append(t)

    mid_brk_trades = [t for t in all_trades if t.get("strategy_id") == "MID_BRK"]
    pnls  = [t["pnl"] for t in mid_brk_trades]
    wins  = [p for p in pnls if p > 0]
    return {
        "trades":     len(pnls),
        "win_rate":   (len(wins) / len(pnls) * 100) if pnls else 0.0,
        "total_pnl":  sum(pnls),
        "expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
    }


def _fmt_row(label: str, s: dict) -> str:
    return (f"  {label:<45} {s['trades']:>7} {s['win_rate']:>5.0f}% "
            f"{s['expectancy']:>+10.2f}$ {s['total_pnl']:>+10.2f}$")


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_MONTHS
    tickers = [a.upper() for a in sys.argv[2:]] or DEFAULT_TICKERS
    if len(sys.argv) > 1 and not sys.argv[1].isdigit():
        tickers = [a.upper() for a in sys.argv[1:]]

    alpaca = AlpacaClient()
    print(f"MID_BRK RVOL CEILING A/B TEST — {months} month(s), tickers: {', '.join(tickers)}\n")

    _orig_ceiling = _mid_brk.RVOL_CEILING

    results = []
    try:
        for label, ceiling in _VARIANTS:
            t0 = time.monotonic()
            print(f"⏳ {label}…", flush=True)
            r = _run_variant(alpaca, tickers, months, ceiling)
            r["label"] = label
            results.append(r)
            print(f"   done ({time.monotonic() - t0:.0f}s) — {r['trades']} trades, "
                  f"WR {r['win_rate']:.0f}%, expectancy ${r['expectancy']:+.2f}", flush=True)
    finally:
        _mid_brk.RVOL_CEILING = _orig_ceiling

    print("\n" + "=" * 100)
    print("RESULT")
    print("=" * 100)
    print(f"{'VARIANT':<45} {'TRADES':>7} {'WIN%':>6} {'EXPECTANCY':>11} {'TOTAL P&L':>11}")
    for r in results:
        print(_fmt_row(r["label"], r))

    print("\nReading this: if any ceiling beats A (no ceiling) on expectancy, that confirms\n"
          "high-RVOL entries are exhaustion spikes, not confirmation, for this setup. If B/C/D\n"
          "also start rejecting most trades (n<10), the sample's too thin to trust the number —\n"
          "note trade count alongside expectancy, not just the dollar figure.\n"
          "SPY/QQQ only — directional, not proof. Live behavior unchanged (flag restored).")


if __name__ == "__main__":
    main()
