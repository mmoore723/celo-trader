"""
ab_test_regime_manager.py — A/B test the regime-gate proposal for VWAP_PB/AFT_REV.

Background
──────────
A proposal argued VWAP_PB and AFT_REV are disabled because nothing enforces
a shared macro-trend direction across strategies, and that adding a
regime_manager.py (15-min EMA9/21 classifier) would fix both. Two of that
proposal's premises didn't hold up when checked: VWAP_PB already has an
ADX >= 25 gate and still lost money with it, and the router already
prevents same-ticker opposing signals via conflict veto. So this is a
genuinely new mechanism, not a documented-missing one — it needs the same
A/B discipline as every other strategy change in this codebase before
anything is re-enabled live.

This script runs the full multi-strategy backtest twice per ticker — once
with regime_manager.REGIME_GATE_ENABLED off (current default) and once with
it on — and reports VWAP_PB and AFT_REV specifically (the only two
strategies this gate touches) plus the portfolio total (to catch any
side effect on other strategies' trade counts via slot competition).

Live trading behavior is unaffected either way — VWAP_PB and AFT_REV stay
disabled in trading/entry.py._STRAT_DEFAULTS regardless of this script's
result. Re-enabling either requires updating that file after reviewing the
numbers here, same as every other change in this project.

Usage:
    python3 ab_test_regime_manager.py            # 3 months, SPY QQQ NVDA
    python3 ab_test_regime_manager.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys
from collections import defaultdict

from broker import AlpacaClient
from backtester import Backtester
import regime_manager as _regime_mgr

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3
_WATCH_STRATEGIES = {"VWAP_PB", "AFT_REV"}


def _run_variant(alpaca, tickers, months, label: str) -> dict:
    watch = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    total_trades, total_pnl = 0, 0.0
    for ticker in tickers:
        print(f"  ⏳ {label}: {ticker}…", flush=True)
        bt     = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        result = bt.run()
        breakdown = result.get("strategy_breakdown") or {}
        total_trades += int(result.get("total_trades", 0))
        total_pnl    += float(result.get("total_pnl", 0.0) or 0.0)
        for sid in _WATCH_STRATEGIES:
            row = breakdown.get(sid, {})
            watch[sid]["trades"] += int(row.get("trades", 0))
            watch[sid]["wins"]   += int(row.get("wins", 0))
            watch[sid]["pnl"]    += float(row.get("pnl", 0.0))
    return {"watch": dict(watch), "total_trades": total_trades, "total_pnl": total_pnl}


def _print_watch(label: str, data: dict) -> None:
    print(f"\n--- {label} ---")
    print(f"Portfolio total: {data['total_trades']} trades, ${data['total_pnl']:+.2f}")
    for sid in sorted(_WATCH_STRATEGIES):
        s = data["watch"].get(sid, {"trades": 0, "wins": 0, "pnl": 0.0})
        n = s["trades"]
        wr = (s["wins"] / n * 100) if n else 0.0
        exp = (s["pnl"] / n) if n else 0.0
        print(f"  {sid:<10} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${s['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade")


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    _orig = _regime_mgr.REGIME_GATE_ENABLED
    try:
        print("\n=== VARIANT A: regime gate OFF (current live default) ===")
        _regime_mgr.REGIME_GATE_ENABLED = False
        off_result = _run_variant(alpaca, tickers, months, "gate-off")

        print("\n=== VARIANT B: regime gate ON (proposed) ===")
        _regime_mgr.REGIME_GATE_ENABLED = True
        on_result = _run_variant(alpaca, tickers, months, "gate-on")
    finally:
        # Always restore — this script must never leave live behavior changed
        _regime_mgr.REGIME_GATE_ENABLED = _orig

    print("\n" + "=" * 72)
    print("REGIME GATE A/B RESULT")
    print("=" * 72)
    _print_watch("GATE OFF", off_result)
    _print_watch("GATE ON", on_result)

    print("\nVerdict (per watched strategy):")
    for sid in sorted(_WATCH_STRATEGIES):
        off_s = off_result["watch"].get(sid, {"trades": 0, "pnl": 0.0})
        on_s  = on_result["watch"].get(sid, {"trades": 0, "pnl": 0.0})
        off_exp = (off_s["pnl"] / off_s["trades"]) if off_s["trades"] else 0.0
        on_exp  = (on_s["pnl"]  / on_s["trades"])  if on_s["trades"]  else 0.0
        if on_s["trades"] < 10:
            print(f"  {sid}: ⚪ too few gated trades ({on_s['trades']}) to trust — do not ship.")
        elif on_exp > off_exp and on_exp > 0:
            print(f"  {sid}: 🟡 improved (${off_exp:+.2f} -> ${on_exp:+.2f}/trade) AND positive. "
                  f"Worth a second sample before re-enabling live.")
        elif on_exp > off_exp:
            print(f"  {sid}: 🟡 improved (${off_exp:+.2f} -> ${on_exp:+.2f}/trade) but still negative. "
                  f"Do not re-enable yet.")
        else:
            print(f"  {sid}: 🔴 no improvement (${off_exp:+.2f} -> ${on_exp:+.2f}/trade). "
                  f"Regime gate did not fix it.")

    print("\nLive bot behavior is unchanged by this script (flag restored).")
    print("Re-enabling VWAP_PB/AFT_REV requires editing trading/entry.py")
    print("_STRAT_DEFAULTS after reviewing these numbers — not automatic.")


if __name__ == "__main__":
    main()
