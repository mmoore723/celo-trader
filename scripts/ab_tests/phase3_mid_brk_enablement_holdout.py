"""Measure the *portfolio* impact of enabling MID_BRK on a locked date range.

The older MID_BRK experiments answer narrower questions (for example, whether
an RVOL ceiling changes MID_BRK's own trade expectancy).  That is useful for
diagnosis, but it cannot answer the production decision: when MID_BRK claims
the single-trade slot, does the whole strategy portfolio become better or
worse?  This runner compares the current enabled set with the identical set
plus MID_BRK and reports both portfolio and MID_BRK-specific results.

It is read-only: settings are snapshotted by each Backtester and the changed
strategy set exists only on that in-memory Backtester instance.

Example:
    python3 scripts/ab_tests/phase3_mid_brk_enablement_holdout.py \
        --start 2026-07-01 --end 2026-08-01
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from broker import get_clients
from backtester import Backtester


DEFAULT_TICKERS = ("SPY", "QQQ", "NVDA", "AAPL", "META")


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """Return only decision-relevant, JSON-safe portfolio evidence."""
    breakdown = result.get("strategy_breakdown") or {}
    return {
        "return_pct": round(float(result.get("total_return", 0.0)), 3),
        "pnl": round(float(result.get("total_pnl", 0.0)), 2),
        "trades": int(result.get("total_trades", 0)),
        "expectancy": round(float(result.get("expectancy", 0.0)), 2),
        "final_balance": round(float(result.get("final_balance", 0.0)), 2),
        "mid_brk": breakdown.get("MID_BRK", {
            "trades": 0, "wins": 0, "pnl": 0.0,
        }),
    }


def _run(
    alpaca: Any, ticker: str, start_date: date, end_date: date, enable_mid: bool,
) -> dict[str, Any]:
    months = max(1, (end_date - start_date).days // 30 + 1)
    backtest = Backtester(
        alpaca, ticker, months=months, starting_capital=5000.0,
        direction="both", start_date=start_date, end_date=end_date,
    )
    if enable_mid:
        backtest.enabled_strategies = set(backtest.enabled_strategies) | {"MID_BRK"}
    result = backtest.run()
    if result.get("error"):
        return {"error": result["error"]}
    return _summary(result)


def _delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("error") or candidate.get("error"):
        return {}
    return {
        "pnl": round(candidate["pnl"] - baseline["pnl"], 2),
        "trades": candidate["trades"] - baseline["trades"],
        "expectancy": round(candidate["expectancy"] - baseline["expectancy"], 2),
        "return_pct": round(candidate["return_pct"] - baseline["return_pct"], 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--start", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Exclusive YYYY-MM-DD")
    args = parser.parse_args()
    start_date, end_date = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end_date <= start_date:
        parser.error("--end must be after --start")

    alpaca, _ = get_clients()
    panel: list[dict[str, Any]] = []
    for raw_ticker in args.tickers:
        ticker = raw_ticker.upper()
        print(f"Running {ticker}: current portfolio…", flush=True)
        baseline = _run(alpaca, ticker, start_date, end_date, enable_mid=False)
        print(f"Running {ticker}: portfolio + MID_BRK…", flush=True)
        candidate = _run(alpaca, ticker, start_date, end_date, enable_mid=True)
        row = {
            "ticker": ticker,
            "baseline": baseline,
            "with_mid_brk": candidate,
            "delta": _delta(baseline, candidate),
        }
        panel.append(row)
        print(json.dumps(row), flush=True)

    valid = [r for r in panel if r["delta"]]
    totals = {
        "tickers": len(valid),
        "portfolio_pnl_delta": round(sum(r["delta"]["pnl"] for r in valid), 2),
        "trade_delta": sum(r["delta"]["trades"] for r in valid),
        "mid_brk_trades": sum(
            int(r["with_mid_brk"].get("mid_brk", {}).get("trades", 0)) for r in valid
        ),
        "mid_brk_pnl": round(sum(
            float(r["with_mid_brk"].get("mid_brk", {}).get("pnl", 0.0)) for r in valid
        ), 2),
    }
    print(json.dumps({"panel": panel, "totals": totals}), flush=True)


if __name__ == "__main__":
    main()
