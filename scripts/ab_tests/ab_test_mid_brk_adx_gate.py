"""
ab_test_mid_brk_adx_gate.py — A/B test removing MID_BRK from
regime_manager.ADX_GATED_STRATEGIES.

Triggered by diag_mid_brk_adx_funnel.py (2026-07-20 run): the ADX>=25 gate
blocks 42% of MID_BRK's raw signals (154/364), and those blocked signals
were SLIGHTLY BETTER quality than the ones that survive (41% worked vs 35%,
avg 60m forward move -0.005% vs -0.024%) — the gate is filtering out signals
that were, if anything, marginally better than what it lets through. That's
a signal-QUALITY read, not a P&L read; this script tests the thing that
actually matters — real expectancy with the gate on vs. off — the same way
every other change here gets tested: built OFF by default, flipped,
compared, restored regardless of outcome. Live bot behavior is unchanged by
running this script.

Usage:
    python3 ab_test_mid_brk_adx_gate.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_mid_brk_adx_gate.py 6 SPY QQQ NVDA AAPL TSLA AMD META AMZN MSFT GOOGL
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
import strategy_router
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    trades, wins, pnl = 0, 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        if result.get("error"):
            # FIX: previously this was swallowed silently — a data-fetch
            # failure (yfinance missing AND Alpaca fallback also failing)
            # looked identical to "MID_BRK legitimately took 0 trades."
            # Surface it so a 0/0 result is diagnosable, not just a mystery.
            print(f"     ❌ {ticker}: {result['error']}")
            continue
        row    = (result.get("strategy_breakdown") or {}).get("MID_BRK", {})
        trades += int(row.get("trades", 0))
        wins   += int(row.get("wins", 0))
        pnl    += float(row.get("pnl", 0.0))
    return {"trades": trades, "wins": wins, "pnl": pnl}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    # CORRECTED 2026-07-23: this used to patch backtester.ADX_GATED_STRATEGIES,
    # but backtester.py no longer imports that name directly (only ADX_MIN +
    # compute_adx_series) since entry detection was rewritten to run through
    # strategy_router.route_signals() at 1-min resolution. The actual gate
    # check now lives in strategy_router.py's route_signals() (`if sid in
    # ADX_GATED_STRATEGIES`), reading its OWN module-level name — that's the
    # one that has to be patched for this to do anything. Old target caused
    # AttributeError: module 'backtester' has no attribute 'ADX_GATED_STRATEGIES'.
    _orig = strategy_router.ADX_GATED_STRATEGIES
    try:
        print("\n=== VARIANT A: MID_BRK ADX-gated (current live default) ===")
        strategy_router.ADX_GATED_STRATEGIES = _orig   # unchanged — MID_BRK included
        old_result = _run_variant(alpaca, tickers, months, "ADX-gated")

        print("\n=== VARIANT B: MID_BRK exempted from the ADX>=25 gate ===")
        strategy_router.ADX_GATED_STRATEGIES = _orig - {"MID_BRK"}
        new_result = _run_variant(alpaca, tickers, months, "ADX-exempt")
    finally:
        # Always restore — this script must never leave live behavior changed
        strategy_router.ADX_GATED_STRATEGIES = _orig

    def _report(name: str, d: dict) -> None:
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        print(f"{name:<28} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")

    print("\n" + "=" * 78)
    print("MID_BRK ADX-GATE A/B RESULT")
    print("=" * 78)
    _report("ADX-GATED (old, live default)", old_result)
    _report("ADX-EXEMPT (new)", new_result)

    print("\nVerdict:")
    if new_result["trades"] < 10:
        print("  ⚪ Too few trades in the new variant to trust — do not ship yet.")
    else:
        old_exp = (old_result["pnl"] / old_result["trades"]) if old_result["trades"] else 0.0
        new_exp = (new_result["pnl"] / new_result["trades"]) if new_result["trades"] else 0.0
        if new_exp > old_exp and new_exp > 0:
            print(f"  🟢 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) and positive — worth shipping.")
        elif new_exp > old_exp:
            print(f"  🟡 Improved (${old_exp:+.2f} -> ${new_exp:+.2f}/trade) but still negative — do not ship.")
        else:
            print(f"  🔴 No improvement (${old_exp:+.2f} -> ${new_exp:+.2f}/trade). ADX gate is doing its job — do not ship.")

    print("\nLive bot behavior is unchanged by this script (ADX_GATED_STRATEGIES restored).")


if __name__ == "__main__":
    main()
