"""
diag_strategy_features.py — generalized winner-vs-loser feature-gap
diagnostic for ANY strategy, not just TREND_CONT.

This replaces writing a new one-off diag_<strategy>_features.py every time —
the pattern that already worked once (diagnostics_archive/
diag_trend_cont_features.py found TREND_CONT winners avg 4 bars_ago vs
losers' 9, which became a real shipped fix, +$41->+$73/trade) generalizes
cleanly: dump every trade for one strategy from a real backtest with its
entry-time RVOL, confidence, and whatever structure metadata that
strategy's entry_meta carries, split by win/loss, and look for a real gap.

Usage:
    python3 diag_strategy_features.py AFT_REV                     # 3mo, SPY QQQ NVDA
    python3 diag_strategy_features.py AFT_REV 2 SPY QQQ NVDA AAPL TSLA AMD META AMZN MSFT GOOGL NFLX AVGO
    python3 diag_strategy_features.py VWAP_PB 2 SPY QQQ NVDA ...
    python3 diag_strategy_features.py TREND_CONT 2 SPY QQQ NVDA ...
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def _avg(rows: list[dict], key: str) -> float:
    vals = [r.get(key, 0.0) for r in rows]
    return sum(vals) / len(vals) if vals else 0.0


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 diag_strategy_features.py STRATEGY_ID [months] [tickers...]")
        print("e.g.:  python3 diag_strategy_features.py AFT_REV 2 SPY QQQ NVDA AAPL TSLA")
        return

    strategy_id = sys.argv[1].upper()
    months      = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MONTHS
    tickers     = sys.argv[3:] or DEFAULT_TICKERS
    alpaca      = AlpacaClient()

    all_trades: list[dict] = []
    for ticker in tickers:
        print(f"⏳ {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.run()
        for t in bt.trades:
            if t.get("strategy_id") == strategy_id:
                t = dict(t)
                t["ticker"] = ticker
                all_trades.append(t)

    print("\n" + "=" * 110)
    print(f"{strategy_id} — {len(all_trades)} trade(s), {months} month(s), {len(tickers)} ticker(s)")
    print("=" * 110)
    if not all_trades:
        print(f"No {strategy_id} trades in this window — nothing to compare. Either the "
              f"strategy is legitimately low-frequency, or something upstream (a gate, "
              f"session window, confidence floor) is suppressing it entirely — check "
              f"diag_strategy_replay.py or a *_session_scan.py-style raw signal count next.")
        return

    # Collect every numeric key that shows up in ANY trade's entry_meta —
    # strategy-agnostic, so this works whether it's TREND_CONT's
    # lh_depth_pct/bars_ago, MID_BRK's consolidation range, or anything else.
    meta_keys: set[str] = set()
    for t in all_trades:
        for k, v in (t.get("entry_meta") or {}).items():
            if isinstance(v, (int, float)):
                meta_keys.add(k)
    meta_keys_sorted = sorted(meta_keys)

    print(f"\n{'DATE':<11} {'TICKER':<6} {'DIR':<8} {'RVOL':>5} {'CONF':>5} {'HELD(m)':>8} {'P&L':>9}  "
          + " ".join(f"{k:>14}" for k in meta_keys_sorted) + "  EXIT")
    print("-" * (70 + 15 * len(meta_keys_sorted)))
    for t in sorted(all_trades, key=lambda x: (x.get("date", ""), x.get("entry_hour", 0))):
        meta = t.get("entry_meta", {}) or {}
        meta_str = " ".join(
            f"{meta.get(k, 0.0):>14.2f}" if isinstance(meta.get(k), (int, float)) else f"{'—':>14}"
            for k in meta_keys_sorted
        )
        print(f"{t.get('date',''):<11} {t.get('ticker',''):<6} {t.get('direction',''):<8} "
              f"{t.get('entry_rvol',0):>5.2f} {t.get('entry_confidence',0):>5.2f} "
              f"{t.get('held_minutes',0):>8.1f} {t.get('pnl',0):>+9.2f}  {meta_str}  {t.get('exit_reason','')}")

    wins   = [t for t in all_trades if t["pnl"] > 0]
    losses = [t for t in all_trades if t["pnl"] <= 0]

    print("\n" + "=" * 110)
    print("WIN vs LOSS averages (look for a real dividing line here)")
    print("=" * 110)
    header = f"{'':<20} {'N':>4} {'avg RVOL':>10} {'avg conf':>10} {'avg held(m)':>12}"
    for k in meta_keys_sorted:
        header += f" {('avg ' + k):>16}"
    print(header)

    for label, rows in (("WINS", wins), ("LOSSES", losses)):
        line = f"{label:<20} {len(rows):>4} {_avg(rows,'entry_rvol'):>10.2f} " \
               f"{_avg(rows,'entry_confidence'):>10.2f} {_avg(rows,'held_minutes'):>12.1f}"
        for k in meta_keys_sorted:
            vals = [(r.get('entry_meta') or {}).get(k) for r in rows]
            vals = [v for v in vals if isinstance(v, (int, float))]
            avg_v = sum(vals) / len(vals) if vals else 0.0
            line += f" {avg_v:>16.2f}"
        print(line)

    print(f"\nWin rate: {len(wins)}/{len(all_trades)} ({len(wins)/len(all_trades)*100:.0f}%)  "
          f"Total P&L: ${sum(t['pnl'] for t in all_trades):+.2f}")

    print("\nRead this as: whichever column shows the biggest gap between WINS and LOSSES")
    print("is a real discriminator worth gating on — propose it as a specific, named")
    print("threshold change, then A/B test it (build ab_test_<strategy>_<change>.py) before")
    print("shipping, same as every other change in this project. If NOTHING shows a clean")
    print("gap, that's real evidence this setup doesn't have enough edge with these features")
    print(f"alone — a sign {strategy_id} may need a structurally different entry condition, not a")
    print("threshold tweak.")


if __name__ == "__main__":
    main()
