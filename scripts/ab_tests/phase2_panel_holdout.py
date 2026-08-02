"""Compare main-only and paper-only opportunity cohorts on one locked holdout.

This is deliberately process-local: it temporarily replaces only the router
gate used by this script, then restores it.  It never writes settings or
touches the running paper bot.

Example:
  python scripts/ab_tests/phase2_panel_holdout.py --tickers QQQ NVDA AAPL META
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

# Allow direct execution from scripts/ab_tests as documented below.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import router_gates
import backtester.core as backtester_core

from api.backtest_jobs import _to_result
from api.models.backtest import BacktestRequest, BacktestResult


DEFAULT_TICKERS = ("QQQ", "NVDA", "AAPL", "META")
DEFAULT_START = "2026-07-15"
DEFAULT_END = "2026-08-01"
DEFAULT_OPPORTUNITY_FLOOR = 0.70


def _main_only_floor(signals: list, ticker: str, min_confidence: float, quiet: bool = False) -> list:
    """The production main confidence floor, without the paper cohort."""
    return [signal for signal in signals if signal.confidence >= min_confidence]


def _opportunity_floor(floor: float):
    """Create a process-local cohort gate for one explicit test floor."""
    def _apply(signals: list, ticker: str, min_confidence: float, quiet: bool = False) -> list:
        for signal in signals:
            if floor <= signal.confidence < min_confidence:
                signal.tier = "opportunity"
        return [signal for signal in signals if signal.confidence >= min_confidence or signal.confidence >= floor]
    return _apply


def _tier_pnl(result: BacktestResult) -> dict[str, float]:
    totals = {"main": 0.0, "opportunity": 0.0}
    for trade in result.trades:
        tier = trade.get("entry_meta", {}).get("tier", "main")
        if tier in totals:
            totals[tier] += float(trade.get("pnl", 0.0))
    return {tier: round(pnl, 2) for tier, pnl in totals.items()}


def _summary(result: BacktestResult) -> dict[str, Any]:
    return {
        "return_pct": round(result.total_return_pct, 3),
        "trades": result.total_trades,
        "final_balance": round(result.final_balance, 2),
        "tier_pnl": _tier_pnl(result),
        "error": result.error,
    }


def _request(ticker: str, start: str, end: str) -> BacktestRequest:
    return BacktestRequest(
        ticker=ticker,
        months=2,
        start_date=start,
        end_date=end,
        starting_capital=5000,
        direction="both",
    )


def compare_ticker(ticker: str, start: str, end: str, opportunity_floor: float) -> dict[str, Any]:
    request = _request(ticker, start, end)
    original_floor = router_gates.apply_confidence_floor
    original_settings = backtester_core.get_settings
    try:
        router_gates.apply_confidence_floor = _opportunity_floor(opportunity_floor)
        # Enable the causal ranking window only for this process-local arm.
        # This exercises the same scheduler that live paper trading uses while
        # leaving the saved production setting untouched.
        def _scheduled_settings() -> dict:
            settings = dict(original_settings())
            settings["paper_trading"] = True
            settings["opportunity_tier_enabled"] = True
            return settings
        backtester_core.get_settings = _scheduled_settings
        opportunity = _to_result(request)
        backtester_core.get_settings = original_settings
        router_gates.apply_confidence_floor = _main_only_floor
        main_only = _to_result(request)
    finally:
        router_gates.apply_confidence_floor = original_floor
        backtester_core.get_settings = original_settings

    return {
        "ticker": ticker,
        "opportunity_floor": opportunity_floor,
        "opportunity_mode": "causal_15m_ranked",
        "opportunity": _summary(opportunity),
        "main_only": _summary(main_only),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--opportunity-floor", type=float, default=DEFAULT_OPPORTUNITY_FLOOR)
    args = parser.parse_args()
    if not 0 < args.opportunity_floor < 0.74:
        parser.error("--opportunity-floor must be greater than 0 and below the 0.74 main floor")

    results = []
    for ticker in args.tickers:
        result = compare_ticker(ticker.upper(), args.start, args.end, args.opportunity_floor)
        results.append(result)
        print(json.dumps(result), flush=True)
    print(json.dumps({"panel": results}), flush=True)


if __name__ == "__main__":
    main()
