"""
diag_instant_reversals.py — Find trades that reversed against us immediately.

Triggered by 3 live trades (BAC/SPY, 07/16 10:14-10:17) that each showed
MFE 0.0% and an exit within 0-2 minutes labeled "atr_trail_stop" — meaning
price never moved favorably even once before stopping out. That label is
misleading: the real trailing stop in position_manager.py only ARMS after
5 minutes AND +15% option gain (_MIN_TRAIL_WARMUP_MIN, _trail_profit_gate).
A trade closed in under 2 minutes with 0% MFE never reached that gate, so
what actually fired was the STATIC initial_atr_stop set on the first tick
(position_manager.py line ~528) — a real stop, just mislabeled in the exit
reason string, which made a 3-trade sample look like a "trailing stop bug"
when it's really an entry-quality question: did the strategy enter exactly
as the move was already exhausting?

This script queries the REAL trade history directly (not a backtest replay
— backtester.py's exit simulation doesn't necessarily match position_manager.py
tick-for-tick, and the point is to diagnose what live trading actually did),
and flags every closed trade with:
  held_minutes <= 3   AND   MFE% <= 1.0%
grouped by strategy_id, ticker, and entry hour, so we can see whether this
is concentrated (→ real entry-timing defect in specific strategies) or
evenly spread (→ just normal option-premium noise, not a design flaw).

Run this on the box where the live/paper DB actually lives (EC2), not
locally — the local mirror does not have real trade history.

Usage:
    python3 diag_instant_reversals.py             # defaults: held<=3min, MFE<=1%
    python3 diag_instant_reversals.py 5 2.0        # held<=5min, MFE<=2%
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/
from datetime import datetime

from database import get_conn

DEFAULT_HELD_MIN_MAX = 3.0   # minutes
DEFAULT_MFE_PCT_MAX  = 1.0   # percent


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def main() -> None:
    held_max = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HELD_MIN_MAX
    mfe_max  = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MFE_PCT_MAX

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ticker, strategy_id, entry_price, exit_price,
                   entry_time, exit_time, exit_reason, realized_pnl,
                   peak_price, mae_price
            FROM trades
            WHERE status = 'closed'
              AND exit_time IS NOT NULL
              AND entry_price IS NOT NULL
              AND exit_price IS NOT NULL
            ORDER BY entry_time
            """
        ).fetchall()

    flagged = []
    for r in rows:
        try:
            et = _parse_iso(r["entry_time"])
            xt = _parse_iso(r["exit_time"])
        except Exception:
            continue
        held_min = (xt - et).total_seconds() / 60.0
        entry_p  = float(r["entry_price"])
        peak_p   = float(r["peak_price"]) if r["peak_price"] is not None else entry_p
        mfe_pct  = (peak_p - entry_p) / entry_p * 100.0 if entry_p else 0.0

        if held_min <= held_max and mfe_pct <= mfe_max:
            flagged.append({
                "id": r["id"], "ticker": r["ticker"], "strategy_id": r["strategy_id"],
                "entry_hour": et.hour, "held_min": held_min, "mfe_pct": mfe_pct,
                "entry_price": entry_p, "exit_price": float(r["exit_price"]),
                "pnl": r["realized_pnl"], "exit_reason": r["exit_reason"],
                "entry_time": r["entry_time"],
            })

    print("=" * 100)
    print(f"TOTAL CLOSED TRADES: {len(rows)}")
    print(f"INSTANT-REVERSAL FLAG: held <= {held_max:.0f}min AND MFE <= {mfe_max:.1f}%  "
          f"→ {len(flagged)} trade(s) ({len(flagged) / len(rows) * 100 if rows else 0:.1f}% of all closed trades)")
    print("=" * 100)

    if not flagged:
        print("No trades match — the 3 seen in the journal screenshot may just be normal variance.")
        return

    print(f"{'DATE':<11} {'TIME':<9} {'TICKER':<6} {'STRAT':<11} {'HELD(m)':>8} "
          f"{'MFE%':>6} {'ENTRY':>7} {'EXIT':>7} {'P&L':>9}  EXIT REASON")
    print("-" * 100)
    for t in flagged:
        d, tm = t["entry_time"][:10], t["entry_time"][11:19]
        print(f"{d:<11} {tm:<9} {t['ticker']:<6} {t['strategy_id']:<11} {t['held_min']:>8.1f} "
              f"{t['mfe_pct']:>6.2f} {t['entry_price']:>7.2f} {t['exit_price']:>7.2f} "
              f"{t['pnl']:>+9.2f}  {t['exit_reason']}")

    # ── Group by strategy ─────────────────────────────────────────────────────
    by_strat: dict[str, list] = {}
    for t in flagged:
        by_strat.setdefault(t["strategy_id"], []).append(t)
    print("\nBy strategy:")
    for sid, trades in sorted(by_strat.items(), key=lambda kv: -len(kv[1])):
        total_pnl = sum(t["pnl"] or 0.0 for t in trades)
        print(f"  {sid:<11} {len(trades):>3} trade(s)  total=${total_pnl:>+9.2f}")

    # ── Group by entry hour ───────────────────────────────────────────────────
    by_hour: dict[int, int] = {}
    for t in flagged:
        by_hour[t["entry_hour"]] = by_hour.get(t["entry_hour"], 0) + 1
    print("\nBy entry hour:")
    for h in sorted(by_hour):
        print(f"  {h:02d}:00  —  {by_hour[h]} trade(s)")

    print("\nInterpretation guide:")
    print("  - Concentrated in one strategy → that strategy's entry logic lacks a")
    print("    confirmation-bar requirement (single-bar trigger, no follow-through check).")
    print("  - Spread evenly across strategies/hours → likely just option-premium bid/ask")
    print("    noise on thin-liquidity contracts, not a fixable entry-timing defect.")
    print("  - Exit reason 'atr_trail_stop' on a sub-3-min trade is ALWAYS the static")
    print("    initial_atr_stop (position_manager.py), never the armed trailing stop —")
    print("    the label is misleading and should be split in exit-reason reporting.")


if __name__ == "__main__":
    main()
