"""
diag_risk_math.py — Cross-check risk.py's R:R gate and stop-tightening
schedule against what real (backtested-with-real-logic) trades actually show.

Answers:
  1. Does the realized win/loss $ ratio roughly match MIN_RR_RATIO
     (1.2 small-account / 1.6 professional)? If wins are much smaller than
     the gate's implied ratio, targets aren't being reached before time/other
     exits fire, and the gate is optimistic vs reality.
  2. When trades exit via "stop_loss", how long were they held? Compare
     against the tightening schedule (20% at 0-14min, tightening 5pp per
     15min, floor 10%) to see if the schedule is cutting trades before they
     had room to work, or letting losers run too long.
  3. Exit-reason mix per strategy — dominated by stage1_50pct (working) vs
     stop_loss/time_exit (not working) vs trailing stops.

Usage:
    python3 diag_risk_math.py            # 6 months, SPY QQQ NVDA
    python3 diag_risk_math.py 6 SPY QQQ NVDA AAPL TSLA AMD META AMZN MSFT GOOGL
"""

from __future__ import annotations

import sys
from collections import defaultdict

from broker import AlpacaClient
from backtester import Backtester
from risk import RiskManager

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA"]
DEFAULT_MONTHS = 6


def main() -> None:
    months = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MONTHS
    tickers = sys.argv[2:] or DEFAULT_TICKERS
    alpaca = AlpacaClient()
    rm = RiskManager()

    all_trades = []
    for ticker in tickers:
        print(f"⏳ {ticker}…", flush=True)
        bt = Backtester(alpaca, ticker, months=months, starting_capital=5000.0, direction="both")
        bt.run()
        for t in bt.trades:
            t = dict(t)
            t["ticker"] = ticker
            all_trades.append(t)

    print("\n" + "=" * 90)
    print(f"RISK MATH CROSS-CHECK — {len(all_trades)} trade(s), {months} months, "
          f"tickers={tickers}")
    print(f"Configured gate: MIN_RR small-account={1.2}  professional={1.6}   "
          f"stop schedule: {int(rm.ORB_STOP_PCT*100)}% → floor {int(rm.STOP_FLOOR_PCT*100)}%, "
          f"tightens {rm.STOP_TIGHTEN_STEP*100:.0f}pp every {rm.STOP_TIGHTEN_INTERVAL}min")
    print("=" * 90)

    if not all_trades:
        print("No trades — nothing to check.")
        return

    # 1. Win/loss $ ratio vs configured MIN_RR
    per_strat = defaultdict(lambda: {"wins": [], "losses": []})
    for t in all_trades:
        pnl = t.get("pnl", 0.0)
        sid = t.get("strategy_id", "UNKNOWN")
        (per_strat[sid]["wins"] if pnl > 0 else per_strat[sid]["losses"]).append(pnl)

    print(f"\n{'STRATEGY':<12} {'AVG WIN':>9} {'AVG LOSS':>9} {'REALIZED W:L':>13} "
          f"{'GATE (1.2/1.6)':>15}")
    print("-" * 90)
    for sid, d in sorted(per_strat.items()):
        avg_w = sum(d["wins"]) / len(d["wins"]) if d["wins"] else 0.0
        avg_l = abs(sum(d["losses"]) / len(d["losses"])) if d["losses"] else 0.0
        realized_rr = (avg_w / avg_l) if avg_l else float("inf")
        print(f"{sid:<12} {avg_w:>+9.2f} {avg_l:>9.2f} {realized_rr:>12.2f}x "
              f"{'':>15}")

    # 2. Held time on stop_loss exits vs tightening schedule
    print("\nHELD TIME on stop_loss exits (schedule: 20%@0-14m → tightens 5pp/15min → floor 10%):")
    stop_trades = [t for t in all_trades if "stop" in str(t.get("exit_reason", "")).lower()]
    if stop_trades:
        held = sorted(t.get("held_minutes", 0) for t in stop_trades)
        n = len(held)
        print(f"  n={n}  median={held[n//2]:.1f}m  min={held[0]:.1f}m  max={held[-1]:.1f}m")
        buckets = {"0-14m": 0, "15-29m": 0, "30-44m": 0, "45m+": 0}
        for m in held:
            if m < 15: buckets["0-14m"] += 1
            elif m < 30: buckets["15-29m"] += 1
            elif m < 45: buckets["30-44m"] += 1
            else: buckets["45m+"] += 1
        for k, v in buckets.items():
            print(f"    {k:<8} {v}")
    else:
        print("  No stop_loss exits found.")

    # 3. Exit-reason mix per strategy
    print("\nEXIT-REASON MIX per strategy:")
    reason_by_strat = defaultdict(lambda: defaultdict(int))
    for t in all_trades:
        reason_by_strat[t.get("strategy_id", "UNKNOWN")][t.get("exit_reason", "unknown")] += 1
    for sid, reasons in sorted(reason_by_strat.items()):
        total = sum(reasons.values())
        parts = ", ".join(f"{r}={n} ({n/total*100:.0f}%)" for r, n in
                           sorted(reasons.items(), key=lambda kv: -kv[1]))
        print(f"  {sid:<12} {parts}")

    print("\nRead it as: if REALIZED W:L is well under the configured gate (1.2/1.6x),")
    print("either targets rarely get hit before another exit fires, or losers are")
    print("bigger than the stop schedule implies (check held-time buckets above for")
    print("stop_loss exits firing later than 0-14m, which would mean the tightening")
    print("schedule isn't clamping losers as fast as designed).")


if __name__ == "__main__":
    main()
