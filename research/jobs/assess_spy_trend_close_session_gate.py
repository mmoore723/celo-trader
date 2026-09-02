#!/usr/bin/env python3
"""Assess blocking new SPY Trend entries after 3:00 PM Eastern.

This is a retrospective discovery study.  It uses the same paid ask/bid,
cost, sizing, and concurrency model as the launch-readiness scorecard, but it
must not change production from this archive alone.  A passing result creates
a prospective candidate rather than a deployable rule.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from research.jobs.evaluate_reviewed_allocation_grid import (
    apply_current_portfolio_policy,
    segment,
)
from research.jobs.evaluate_reviewed_launch_readiness import _run
from research.jobs.evaluate_reviewed_strategy_selector import (
    STRATEGY_SPECS,
    load_reviewed_markouts,
)


MARKET_TIMEZONE = ZoneInfo("America/New_York")
SPY_TREND_ID = "V2_SPY_TREND_CONT"
CUTOFF_ET = time(15, 0)


def _market_clock(value: object) -> time:
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is not None:
        moment = moment.astimezone(MARKET_TIMEZONE)
    return moment.time().replace(tzinfo=None)


def apply_close_session_gate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove only new SPY Trend entries at or after 3:00 PM Eastern."""
    return [
        row
        for row in rows
        if not (
            str(row.get("ticker") or "").upper() == "SPY"
            and str(row.get("strategy_id") or "").upper() == SPY_TREND_ID
            and _market_clock(row["entry_time"]) >= CUTOFF_ET
        )
    ]


def _period_summary(
    rows: list[dict[str, Any]], *, starting_capital: float, max_positions: int,
) -> dict[str, Any]:
    return _run(
        rows,
        strategy_ids=frozenset(STRATEGY_SPECS),
        starting_capital=starting_capital,
        slippage=.01,
        max_positions=max_positions,
    )


def _pf(summary: dict[str, Any]) -> float:
    value = summary["profit_factor_after_all_costs"]
    return float("inf") if value == "inf" else float(value or 0)


def summarize_prospective_gate(report: dict[str, Any]) -> dict[str, Any]:
    """Measure the independently collected cohort that the veto would skip."""
    strategy = report.get("by_strategy", {}).get(SPY_TREND_ID, {})
    details = strategy.get("episodes_detail", []) if isinstance(strategy, dict) else []
    late = [
        row for row in details
        if isinstance(row, dict) and _market_clock(row.get("observed_at")) >= CUTOFF_ET
    ]
    pnls = [float(row.get("net_pnl_one_contract") or 0) for row in late]
    returns = [float(row.get("net_return_pct") or 0) for row in late]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    profit_factor: float | str | None
    if losses > 0:
        profit_factor = round(gains / losses, 4)
    elif gains > 0:
        profit_factor = "inf"
    else:
        profit_factor = None
    days = len({datetime.fromisoformat(str(row["observed_at"])).date() for row in late})
    gates = {
        "at_least_10_independent_episodes": len(late) >= 10,
        "at_least_10_trading_days": days >= 10,
        "skipped_cohort_loses_money": sum(pnls) < 0,
        "skipped_cohort_average_and_median_negative": (
            bool(returns)
            and sum(returns) / len(returns) < 0
            and median(returns) < 0
        ),
        "skipped_cohort_profit_factor_below_one": (
            isinstance(profit_factor, (int, float)) and profit_factor < 1
        ),
    }
    return {
        "source": report.get("database"),
        "measurement": "Independent Tradier candidate episodes collected outside the paid historical archive.",
        "late_episodes": len(late),
        "trading_days": days,
        "wins": sum(value > 0 for value in pnls),
        "net_pnl_one_contract": round(sum(pnls), 2),
        "average_net_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "median_net_return_pct": round(median(returns), 4) if returns else None,
        "profit_factor_after_costs": profit_factor,
        "gates": gates,
        "confirmed": all(gates.values()),
    }


def build_report(
    rows: list[dict[str, Any]], *, validation_start: date,
    holdout_start: date, starting_capital: float = 5_000.0,
    max_positions: int = 3,
    prospective_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = apply_current_portfolio_policy(rows)
    candidate = apply_close_session_gate(current)
    periods = {
        "eligibility": (None, validation_start),
        "validation": (validation_start, holdout_start),
        "holdout": (holdout_start, None),
    }
    results: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for period_name, (start, end) in periods.items():
        baseline_rows = segment(current, start, end)
        candidate_rows = segment(candidate, start, end)
        baseline = _period_summary(
            baseline_rows, starting_capital=starting_capital,
            max_positions=max_positions,
        )
        proposed = _period_summary(
            candidate_rows, starting_capital=starting_capital,
            max_positions=max_positions,
        )
        results[period_name] = {
            "current_policy": baseline,
            "block_spy_trend_after_1500_et": proposed,
            "candidate_rows_removed": len(baseline_rows) - len(candidate_rows),
            "net_pnl_delta": round(
                proposed["net_pnl_after_all_costs"]
                - baseline["net_pnl_after_all_costs"], 2,
            ),
            "profit_factor_delta": round(_pf(proposed) - _pf(baseline), 4),
            "drawdown_delta_pct": round(
                proposed["cash_cost_basis_max_drawdown_pct"]
                - baseline["cash_cost_basis_max_drawdown_pct"], 4,
            ),
        }
        gates[period_name] = {
            "pnl_not_lower": (
                proposed["net_pnl_after_all_costs"]
                >= baseline["net_pnl_after_all_costs"]
            ),
            "profit_factor_not_lower": _pf(proposed) >= _pf(baseline),
            "drawdown_not_higher": (
                proposed["cash_cost_basis_max_drawdown_pct"]
                <= baseline["cash_cost_basis_max_drawdown_pct"]
            ),
        }

    removed = len(current) - len(candidate)
    consistent = removed >= 20 and all(
        all(period_gates.values()) for period_gates in gates.values()
    )
    prospective = (
        summarize_prospective_gate(prospective_report)
        if prospective_report is not None else None
    )
    externally_confirmed = bool(prospective and prospective["confirmed"])
    return {
        "purpose": "Test whether stopping new SPY Trend entries after 3:00 PM improves the reviewed portfolio.",
        "complete": True,
        "classification": "retrospective_discovery_only",
        "cutoff_et": "15:00",
        "validation_start": validation_start.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "cost_model": "Exact paid ask/bid plus $0.12 per contract per side, $0.01 adverse slippage each side, and $10 monthly subscription.",
        "results": results,
        "gates": gates,
        "prospective_validation": prospective,
        "decision": {
            "historically_consistent": consistent,
            "externally_confirmed": externally_confirmed,
            "candidate_rows_removed": removed,
            "status": (
                "eligible_for_runtime_review"
                if consistent and externally_confirmed else
                "prospective_collecting"
                if consistent else
                "reject"
            ),
            "runtime_changed": False,
            "reason": (
                "The rule improved or preserved P&L, PF, and drawdown in every archive period and the independent Tradier cohort confirmed that the vetoed episodes lose. It is eligible for explicit runtime review, not automatic activation."
                if consistent and externally_confirmed else
                "The archive result is consistent, but the independent Tradier cohort has not met the sample and loss gates. Keep collecting; do not enable the veto."
                if consistent else
                "The rule did not improve or preserve P&L, PF, and drawdown in every archive period with at least 20 removed candidates."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orb", type=Path, required=True)
    parser.add_argument("--spy-failed-range", type=Path, required=True)
    parser.add_argument("--spy-trend", type=Path, required=True)
    parser.add_argument("--spy-fvg", type=Path, required=True)
    parser.add_argument("--tsla-two-leg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prospective-pf-report", type=Path)
    parser.add_argument("--validation-start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--starting-capital", type=float, default=5_000.0)
    parser.add_argument("--max-positions", type=int, default=3)
    args = parser.parse_args()
    report = build_report(
        load_reviewed_markouts({
            "V2_ORB_PULLBACK": args.orb,
            "V2_SPY_FAILED_RANGE_RECOVERY": args.spy_failed_range,
            "V2_SPY_TREND_CONT": args.spy_trend,
            "V2_SPY_AFTERNOON_FVG": args.spy_fvg,
            "V2_TSLA_TWO_LEG_TREND_PULLBACK": args.tsla_two_leg,
        }),
        validation_start=args.validation_start,
        holdout_start=args.holdout_start,
        starting_capital=args.starting_capital,
        max_positions=args.max_positions,
        prospective_report=(
            json.loads(args.prospective_pf_report.read_text(encoding="utf-8"))
            if args.prospective_pf_report else None
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
