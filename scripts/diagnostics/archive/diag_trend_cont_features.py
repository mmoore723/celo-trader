"""
diag_trend_cont_features.py — What actually separates TREND_CONT winners
from losers?

Raising the confidence floor made things worse (24 trades, 29% WR, -$39.59
expectancy) because a blanket threshold can't tell a good LH/HL re-entry
from a bad one — it just lets more of BOTH through. This dumps every
TREND_CONT trade from a real backtest with its entry-time RVOL, confidence,
and structure metadata (lh_depth_pct/hl_rise_pct, bars_ago) next to its
actual P&L outcome, so we can look for a real dividing line — e.g. "wins
cluster at RVOL > 2.0, losses cluster below that" — instead of guessing at
a single number.

Requires backtester.py's 2026-07-17 change that captures entry_confidence/
entry_rvol/entry_meta on every simulated trade.

Usage:
    python3 diag_trend_cont_features.py            # 3 months, SPY QQQ NVDA
    python3 diag_trend_cont_features.py 6 SPY QQQ NVDA
"""

from __future__ import annotations

import sys

from broker import AlpacaClient
from backtester import Backtester

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS  = 3


def main() -> None:
    months  = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    all_trades = []
    for ticker in tickers:
        print(f"⏳ {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.run()
        for t in bt.trades:
            if t.get("strategy_id") == "TREND_CONT":
                t = dict(t)
                t["ticker"] = ticker
                all_trades.append(t)

    print("\n" + "=" * 110)
    print(f"TREND_CONT — {len(all_trades)} trade(s)")
    print("=" * 110)
    if not all_trades:
        print("No TREND_CONT trades in this window.")
        return

    print(f"{'DATE':<11} {'TICKER':<6} {'DIR':<8} {'RVOL':>5} {'CONF':>5} "
          f"{'DEPTH/RISE%':>11} {'BARS_AGO':>8} {'HELD(m)':>8} {'P&L':>9}  EXIT")
    print("-" * 110)
    for t in sorted(all_trades, key=lambda x: (x.get("date", ""), x.get("entry_hour", 0))):
        meta       = t.get("entry_meta", {}) or {}
        depth_rise = meta.get("lh_depth_pct", meta.get("hl_rise_pct", 0.0))
        bars_ago   = meta.get("bars_ago", 0)
        print(f"{t.get('date',''):<11} {t.get('ticker',''):<6} {t.get('direction',''):<8} "
              f"{t.get('entry_rvol',0):>5.2f} {t.get('entry_confidence',0):>5.2f} "
              f"{depth_rise:>11.2f} {bars_ago:>8} {t.get('held_minutes',0):>8.1f} "
              f"{t.get('pnl',0):>+9.2f}  {t.get('exit_reason','')}")

    wins   = [t for t in all_trades if t["pnl"] > 0]
    losses = [t for t in all_trades if t["pnl"] <= 0]

    def _avg(rows, key):
        vals = [r.get(key, 0.0) for r in rows]
        return sum(vals) / len(vals) if vals else 0.0

    def _avg_meta(rows, keys):
        vals = []
        for r in rows:
            m = r.get("entry_meta", {}) or {}
            for k in keys:
                if k in m:
                    vals.append(m[k])
                    break
        return sum(vals) / len(vals) if vals else 0.0

    print("\n" + "=" * 110)
    print("WIN vs LOSS averages (look for a real dividing line here)")
    print("=" * 110)
    print(f"{'':<20} {'N':>4} {'avg RVOL':>10} {'avg conf':>10} {'avg depth/rise%':>16} {'avg bars_ago':>13}")
    print(f"{'WINS':<20} {len(wins):>4} {_avg(wins,'entry_rvol'):>10.2f} {_avg(wins,'entry_confidence'):>10.2f} "
          f"{_avg_meta(wins, ['lh_depth_pct','hl_rise_pct']):>16.2f} "
          f"{_avg_meta(wins, ['bars_ago']):>13.1f}")
    print(f"{'LOSSES':<20} {len(losses):>4} {_avg(losses,'entry_rvol'):>10.2f} {_avg(losses,'entry_confidence'):>10.2f} "
          f"{_avg_meta(losses, ['lh_depth_pct','hl_rise_pct']):>16.2f} "
          f"{_avg_meta(losses, ['bars_ago']):>13.1f}")

    print("\nRead this as: whichever column shows the biggest gap between WINS")
    print("and LOSSES is the real discriminator — that's what should gate entry,")
    print("not a blanket confidence-floor change. If nothing shows a clean gap,")
    print("that's real evidence TREND_CONT's re-entry setup itself doesn't have")
    print("enough edge to separate winners from losers with these features alone.")


if __name__ == "__main__":
    main()
