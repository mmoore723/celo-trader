#!/usr/bin/env python3
"""Select strategy-group allocations without reading the final holdout.

The study uses exact reviewed paid-option ask entries and same-contract bid
exits.  Candidate allocations are declared in this file.  Earlier history is
the eligibility period, June is the selection/validation period, and July+
remains untouched until one frozen allocation map has been selected.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time
from itertools import product
import json
from pathlib import Path
import random
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from research.jobs.evaluate_reviewed_strategy_selector import (
    LAUNCH_PROFIT_FACTOR,
    STRATEGY_SPECS,
    load_reviewed_markouts,
    simulate_policy,
    summarize_trades,
)


PROVEN = ("V2_SPY_FAILED_RANGE_RECOVERY", "V2_SPY_TREND_CONT")
UNDERPOWERED = ("V2_SPY_AFTERNOON_FVG",)
INCONSISTENT = ("V2_ORB_PULLBACK", "V2_TSLA_TWO_LEG_TREND_PULLBACK")
GRID = {
    "proven": (.05, .10, .15, .20),
    "underpowered": (.05, .10, .15),
    "inconsistent": (.05, .10, .15),
}
MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def allocation_map(proven: float, underpowered: float, inconsistent: float) -> dict[str, float]:
    return {
        **{strategy_id: proven for strategy_id in PROVEN},
        **{strategy_id: underpowered for strategy_id in UNDERPOWERED},
        **{strategy_id: inconsistent for strategy_id in INCONSISTENT},
    }


def apply_current_portfolio_policy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror the deployed 1:45–3:00 SPY Trend slot reservation."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        moment = _moment(row["entry_time"])
        # Paid option fills are timestamped in UTC while the production
        # policy is explicitly defined in Eastern market time.  Comparing the
        # raw UTC clock silently reserved the wrong hours in portfolio replays.
        # Naive legacy fixtures already represent Eastern time.
        market_moment = (
            moment.astimezone(MARKET_TIMEZONE) if moment.tzinfo is not None else moment
        )
        clock = market_moment.time().replace(tzinfo=None)
        if (
            row.get("ticker") == "SPY"
            and row.get("strategy_id") == "V2_SPY_TREND_CONT"
            and time(13, 45) <= clock <= time(15, 0)
        ):
            continue
        kept.append(row)
    return kept


def segment(rows: list[dict[str, Any]], start: date | None, end: date | None) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if (start is None or _moment(row["signal_time"]).date() >= start)
        and (end is None or _moment(row["signal_time"]).date() < end)
    ]


def run_segment(
    rows: list[dict[str, Any]], allocations: dict[str, float], *, starting_capital: float,
) -> dict[str, Any]:
    simulation = simulate_policy(
        rows,
        policy="all_affordable",
        starting_capital=starting_capital,
        allocation_fraction=.15,
        allocation_by_strategy=allocations,
        max_positions=3,
    )
    accepted = simulation.pop("accepted")
    skipped = simulation.pop("skipped")
    simulation["summary"] = summarize_trades(accepted, starting_capital=starting_capital)
    simulation["accepted_trades"] = accepted
    simulation["skipped_decisions"] = skipped
    return simulation


def _factor(summary: dict[str, Any]) -> float:
    value = summary.get("profit_factor")
    if value == "inf":
        return float("inf")
    return float(value or 0)


def eligible(summary: dict[str, Any], *, minimum_trades: int) -> bool:
    return all(eligibility_gates(summary, minimum_trades=minimum_trades).values())


def eligibility_gates(summary: dict[str, Any], *, minimum_trades: int) -> dict[str, bool]:
    """Return every selection gate so rejected allocation maps are auditable."""
    return {
        "minimum_trades": summary.get("trades", 0) >= minimum_trades,
        "positive_pnl": float(summary.get("pnl", 0)) > 0,
        "positive_average_return": float(summary.get("average_return_pct") or 0) > 0,
        "positive_median_return": float(summary.get("median_return_pct") or 0) > 0,
        "profit_factor_at_least_launch_target": _factor(summary) >= LAUNCH_PROFIT_FACTOR,
    }


def _protected_positive(summary: dict[str, Any]) -> dict[str, bool]:
    details = summary.get("by_strategy", {})
    return {
        strategy_id: bool(
            (item := details.get(strategy_id))
            and item.get("trades", 0) > 0
            and float(item.get("pnl", 0)) > 0
            and float(item.get("average_return_pct", 0)) > 0
        )
        for strategy_id in PROVEN
    }


def day_block_bootstrap(rows: list[dict[str, Any]], *, samples: int = 2_000) -> dict[str, Any]:
    by_day: dict[date, float] = defaultdict(float)
    for row in rows:
        by_day[_moment(row["exit_time"]).date()] += float(row["pnl"])
    values = list(by_day.values())
    if not values:
        return {"samples": samples, "days": 0, "probability_positive_pnl_pct": None, "pnl_95pct": None}
    rng = random.Random(20260821)
    draws = sorted(sum(rng.choice(values) for _ in values) for _ in range(samples))
    low = draws[int(samples * .025)]
    high = draws[min(samples - 1, int(samples * .975))]
    return {
        "samples": samples,
        "days": len(values),
        "probability_positive_pnl_pct": round(100 * sum(value > 0 for value in draws) / samples, 2),
        "pnl_95pct": [round(low, 2), round(high, 2)],
    }


def build_report(
    rows: list[dict[str, Any]], *, validation_start: date, holdout_start: date,
    starting_capital: float = 5_000,
) -> dict[str, Any]:
    rows = apply_current_portfolio_policy(rows)
    periods = {
        "eligibility": segment(rows, None, validation_start),
        "validation": segment(rows, validation_start, holdout_start),
        "holdout": segment(rows, holdout_start, None),
    }
    baseline_allocations = allocation_map(.15, .15, .15)
    baseline = {
        name: run_segment(period_rows, baseline_allocations, starting_capital=starting_capital)
        for name, period_rows in periods.items()
    }
    candidates: list[dict[str, Any]] = []
    for proven, underpowered, inconsistent in product(
        GRID["proven"], GRID["underpowered"], GRID["inconsistent"],
    ):
        allocations = allocation_map(proven, underpowered, inconsistent)
        eligibility_run = run_segment(periods["eligibility"], allocations, starting_capital=starting_capital)
        validation_run = run_segment(periods["validation"], allocations, starting_capital=starting_capital)
        eligibility_summary = eligibility_run["summary"]
        validation_summary = validation_run["summary"]
        eligibility_period_gates = eligibility_gates(eligibility_summary, minimum_trades=30)
        validation_period_gates = eligibility_gates(validation_summary, minimum_trades=15)
        protected_strategy_gates = _protected_positive(validation_summary)
        drawdown_gate = (
            float(validation_summary["realized_pnl_max_drawdown"])
            <= float(baseline["validation"]["summary"]["realized_pnl_max_drawdown"]) * 1.10
        )
        passed = all(eligibility_period_gates.values()) and all(validation_period_gates.values()) \
            and all(protected_strategy_gates.values()) and drawdown_gate
        candidates.append({
            "allocations": allocations,
            "group_allocations": {
                "proven": proven,
                "underpowered": underpowered,
                "inconsistent": inconsistent,
            },
            "eligible": passed,
            "selection_gates": {
                "eligibility_period": eligibility_period_gates,
                "validation_period": validation_period_gates,
                "protected_validation_strategies": protected_strategy_gates,
                "validation_drawdown_within_110pct_of_baseline": drawdown_gate,
            },
            "eligibility": eligibility_summary,
            "validation": validation_summary,
        })
    eligible_candidates = [row for row in candidates if row["eligible"]]
    selected = max(
        eligible_candidates,
        key=lambda row: (
            float(row["validation"]["pnl"]),
            _factor(row["validation"]),
            -float(row["validation"]["realized_pnl_max_drawdown"]),
            float(row["validation"]["median_return_pct"]),
        ),
        default=None,
    )
    selected_allocations = selected["allocations"] if selected else baseline_allocations
    holdout = run_segment(periods["holdout"], selected_allocations, starting_capital=starting_capital)
    holdout_summary = holdout["summary"]
    baseline_holdout = baseline["holdout"]["summary"]
    bootstrap = day_block_bootstrap(holdout["accepted_trades"])
    protected = _protected_positive(holdout_summary)
    gates = {
        "selection_available_without_holdout": selected is not None,
        "holdout_at_least_40_trades": holdout_summary["trades"] >= 40,
        "holdout_positive_average_and_median": (
            float(holdout_summary.get("average_return_pct") or 0) > 0
            and float(holdout_summary.get("median_return_pct") or 0) > 0
        ),
        "holdout_profit_factor_at_least_launch_target": (
            _factor(holdout_summary) >= LAUNCH_PROFIT_FACTOR
        ),
        "holdout_protected_strategies_positive": all(protected.values()),
        "holdout_not_lower_pnl_than_flat_15pct": holdout_summary["pnl"] >= baseline_holdout["pnl"],
        "holdout_drawdown_not_worse": (
            holdout_summary["realized_pnl_max_drawdown"]
            <= baseline_holdout["realized_pnl_max_drawdown"]
        ),
        "bootstrap_probability_positive_at_least_80pct": (
            float(bootstrap.get("probability_positive_pnl_pct") or 0) >= 80
        ),
    }
    passed = all(gates.values())
    return {
        "purpose": "Causal strategy-group allocation selection for the five current reviewed paid-option strategies.",
        "complete": True,
        "validation_start": validation_start.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "starting_capital": starting_capital,
        "execution_scope": "Exact paid ask entries, same-contract bid exits, whole contracts, one position per ticker, at most three positions, and the deployed SPY 1:45–3:00 PM slot reservation.",
        "declared_grid": GRID,
        "period_candidate_counts": {name: len(value) for name, value in periods.items()},
        "baseline_flat_15pct": {name: run["summary"] for name, run in baseline.items()},
        "selection_candidates": candidates,
        "selected_before_holdout": selected,
        "holdout": holdout_summary,
        "holdout_bootstrap": bootstrap,
        "decision": {
            "passed": passed,
            "gates": gates,
            "protected_strategy_gates": protected,
            "runtime_changed": False,
            "reason": (
                "Frozen group allocations improved untouched later P&L without increasing drawdown and cleared every robustness gate."
                if passed else
                "The frozen allocation map did not clear every untouched later-data and robustness gate; retain current sizing."
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
    parser.add_argument("--validation-start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--starting-capital", type=float, default=5_000)
    args = parser.parse_args()
    paths = {
        "V2_ORB_PULLBACK": args.orb,
        "V2_SPY_FAILED_RANGE_RECOVERY": args.spy_failed_range,
        "V2_SPY_TREND_CONT": args.spy_trend,
        "V2_SPY_AFTERNOON_FVG": args.spy_fvg,
        "V2_TSLA_TWO_LEG_TREND_PULLBACK": args.tsla_two_leg,
    }
    report = build_report(
        load_reviewed_markouts(paths),
        validation_start=args.validation_start,
        holdout_start=args.holdout_start,
        starting_capital=args.starting_capital,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected": (report["selected_before_holdout"] or {}).get("group_allocations"),
        "baseline_holdout": report["baseline_flat_15pct"]["holdout"],
        "holdout": report["holdout"],
        "bootstrap": report["holdout_bootstrap"],
        "decision": report["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
