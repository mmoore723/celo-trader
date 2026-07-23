"""
ab_test_stage1_target.py — A/B/C tests the stage1 profit-lock threshold
(ORB_STAGE1_GAIN) that fires the "sell 50% of contracts" partial exit.

WHY THIS ONE: run_full_audit.py's win/loss exit-reason breakdown showed
zero winning trades reaching stage1_50pct across multiple strategies —
winners are exiting via peak_giveback/time_cap/momentum_dead before the
profit-lock target is ever reached. Scale-out best practice (see research
cited in chat: lock partial profit at a NEARER, reachable target, then
trail the remainder) suggests the live 50% default may simply be too far
for this account size/timeframe, not that the exit hierarchy itself is
broken.

FIDELITY NOTE: this script tests the CORRECTED baseline. Until today,
backtest_exit_sim.py silently used risk.py's stale class default (25%)
instead of live's real settings-driven default (50%, from config.py's
_DEFAULTS["orb_stage1_gain_pct"] combined with trading/entry.py's
per-request override). That fidelity gap is now fixed — see the comment
block in backtest_exit_sim.py. This test's "current live default" row is
therefore 0.50, not 0.25.

MONKEYPATCH TARGET: backtest_exit_sim.py holds a MODULE-LEVEL singleton
`_risk = RiskManager()` that evaluate_bt_exit() reads via `_risk.should_
exit()`. That instance — not a fresh RiskManager() — is what the
backtester actually calls, so the variant value must be patched onto
THAT instance (backtest_exit_sim._risk.ORB_STAGE1_GAIN), not onto the
risk module's class attribute (risk.RiskManager.ORB_STAGE1_GAIN), which
the running instance no longer reads after entry.py-style instance
overrides.

HONEST LIMITATION: same yfinance ~60-day intraday cap as every other A/B
test this session — no true walk-forward validation, same overlapping
window reused. Treat results as directional, confirm via forward paper
trading before committing to a new default in config.py/risk.py.

Usage:
    python3 ab_test_stage1_target.py                     # 2mo, default tickers
    python3 ab_test_stage1_target.py 2 SPY QQQ NVDA AAPL TSLA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
import backtest_exit_sim
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]
DEFAULT_MONTHS  = 2

# Corrected live default (0.50) plus two nearer/more-reachable candidates,
# spaced out per scale-out research (lock partial profit sooner, trail the
# rest) — not tuned to a target, just testing the shape of the trade-off.
_STAGE1_VARIANTS = [0.50, 0.30, 0.20]


def _run_variant(alpaca, tickers, months) -> dict:
    trades, wins, pnl, stage1_wins = 0, 0, 0.0, 0
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
            if str(row.get("exit_reason", "")).startswith("stage1"):
                stage1_wins += 1 if row.get("pnl", 0) > 0 else 0
    return {"trades": trades, "wins": wins, "pnl": pnl, "stage1_wins": stage1_wins}


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    # Patch the actual runtime instance backtest_exit_sim.evaluate_bt_exit()
    # reads from — NOT risk.RiskManager's class attribute, which the live
    # settings-override pattern (trading/entry.py) already supersedes.
    _orig = backtest_exit_sim._risk.ORB_STAGE1_GAIN
    results = {}
    try:
        for variant in _STAGE1_VARIANTS:
            tag = " (corrected live default)" if variant == _orig else ""
            print(f"\n=== STAGE1 GAIN = {variant:.0%}{tag} ===")
            backtest_exit_sim._risk.ORB_STAGE1_GAIN = variant
            results[variant] = _run_variant(alpaca, tickers, months)
    finally:
        # Always restore — this script must never leave live behavior changed.
        backtest_exit_sim._risk.ORB_STAGE1_GAIN = _orig

    print("\n" + "=" * 82)
    print("STAGE1 PROFIT-LOCK THRESHOLD A/B/C RESULT")
    print("=" * 82)
    for variant, d in results.items():
        n   = d["trades"]
        wr  = (d["wins"] / n * 100) if n else 0.0
        exp = (d["pnl"] / n) if n else 0.0
        tag = " (current)" if variant == _orig else ""
        print(f"stage1={variant:.0%}{tag:<12} trades={n:>4}  win%={wr:>5.1f}%  "
              f"total=${d['pnl']:>+9.2f}  expectancy=${exp:>+8.2f}/trade  "
              f"winning stage1 exits={d['stage1_wins']}")

    print("\nRead this as a DIRECTION, not a verdict — same single overlapping")
    print("backtest window as every other test this session (yfinance's ~60-day")
    print("intraday cap). A better number here means the next step is paper")
    print("trading it for real weeks, not re-running this script and calling it proof.")
    print("\nLive risk.py/config.py are unchanged by this script (ORB_STAGE1_GAIN restored).")


if __name__ == "__main__":
    main()
