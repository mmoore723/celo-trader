"""
ab_test_rr_gate.py — A/B/C/D/E test for the pre-entry R:R gate threshold.

WHY THIS EXISTS (2026-07-22): live's trading/entry.py has always called
risk.evaluate_rr() and blocked any entry below the minimum reward:risk
ratio (1.2x for small accounts, 1.6x once graduated) before sending an
order. backtester.py never called this at all — every backtest run before
today included trades live would have refused to take. Backtester.py now
has this wired in (Backtester.RR_GATE_ENABLED, default True, see
backtester.py's _simulate_day) so backtest and live match by default.

This script answers a DIFFERENT question: given the gate now exists, what
threshold actually produces the best expectancy? Variants below monkeypatch
each Backtester instance's _risk.effective_min_rr() to a fixed value so the
comparison isn't muddied by the balance-based auto/small_account/
professional tier switch — same monkeypatch-restore-in-finally pattern used
by every other ab_test_*.py script this session.

CAVEAT (same as every other A/B test this session): SPY/QQQ, ~2 months,
single overlapping backtest window — directional evidence, not proof. No
walk-forward/out-of-sample split yet.

Usage:
    python3 ab_test_rr_gate.py [months] [TICKER TICKER ...]
    python3 ab_test_rr_gate.py 2 SPY QQQ
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ"]   # the only two tickers the live bot actually
                                    # trades below the $25k phase-2 boundary
DEFAULT_MONTHS  = 2

# (label, gate_enabled, fixed_min_rr_or_None)
# None fixed_rr = gate disabled entirely (variant A, the pre-2026-07-22 control)
_VARIANTS: list[tuple[str, bool, "float | None"]] = [
    ("A: gate OFF (control — pre-fidelity-fix behavior)", False, None),
    ("B: gate ON, min R:R = 1.0x", True, 1.0),
    ("C: gate ON, min R:R = 1.2x (current small-account default)", True, 1.2),
    ("D: gate ON, min R:R = 1.6x (current professional default)", True, 1.6),
    ("E: gate ON, min R:R = 2.0x (stricter)", True, 2.0),
]


def _run_variant(alpaca, tickers: list[str], months: int, gate_enabled: bool,
                  fixed_rr: "float | None") -> dict:
    all_trades: list[dict] = []
    total_blocked = 0
    for ticker in tickers:
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.RR_GATE_ENABLED = gate_enabled
        _orig_effective_min_rr = bt._risk.effective_min_rr
        if gate_enabled and fixed_rr is not None:
            bt._risk.effective_min_rr = lambda *a, **k: fixed_rr
        try:
            result = bt.run()
        finally:
            bt._risk.effective_min_rr = _orig_effective_min_rr   # always restore
        if result.get("error"):
            continue
        for t in result.get("trades", []):
            t = dict(t)
            t["ticker"] = ticker
            all_trades.append(t)
        total_blocked += result.get("diagnostics", {}).get("rr_gate_blocked", 0)

    pnls = [t["pnl"] for t in all_trades]
    wins = [p for p in pnls if p > 0]
    return {
        "trades":     len(pnls),
        "win_rate":   (len(wins) / len(pnls) * 100) if pnls else 0.0,
        "total_pnl":  sum(pnls),
        "expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "rr_gate_blocked": total_blocked,
    }


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_MONTHS
    tickers = [a.upper() for a in sys.argv[2:] if not a.isdigit()] or DEFAULT_TICKERS
    if len(sys.argv) > 1 and not sys.argv[1].isdigit():
        tickers = [a.upper() for a in sys.argv[1:]]

    alpaca = AlpacaClient()
    print(f"R:R GATE A/B TEST — {months} month(s), tickers: {', '.join(tickers)}\n")

    results = []
    for label, gate_enabled, fixed_rr in _VARIANTS:
        t0 = time.monotonic()
        print(f"⏳ {label}…", flush=True)
        r = _run_variant(alpaca, tickers, months, gate_enabled, fixed_rr)
        r["label"] = label
        results.append(r)
        print(f"   done ({time.monotonic() - t0:.0f}s) — {r['trades']} trades, "
              f"WR {r['win_rate']:.0f}%, expectancy ${r['expectancy']:+.2f}, "
              f"blocked {r['rr_gate_blocked']}", flush=True)

    print("\n" + "=" * 100)
    print("RESULT")
    print("=" * 100)
    print(f"{'VARIANT':<55} {'TRADES':>7} {'WIN%':>6} {'EXPECTANCY':>11} {'TOTAL P&L':>11} {'BLOCKED':>8}")
    print("-" * 100)
    for r in results:
        print(f"{r['label']:<55} {r['trades']:>7} {r['win_rate']:>5.0f}% "
              f"{r['expectancy']:>+10.2f}$ {r['total_pnl']:>+10.2f}$ {r['rr_gate_blocked']:>8}")

    print("\nReading this: a stricter gate (higher min R:R) should reduce trade count and\n"
          "raise per-trade expectancy IF the blocked trades were genuinely worse setups.\n"
          "If expectancy barely moves between variants, the R:R gate isn't the lever —\n"
          "look elsewhere. Small overlapping sample (SPY/QQQ only) — directional, not proof.")


if __name__ == "__main__":
    main()
