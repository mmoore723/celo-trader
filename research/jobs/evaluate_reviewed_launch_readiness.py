#!/usr/bin/env python3
"""Audit the reviewed bot against the explicit PF 1.50 and $5k growth goal.

This report does not tune a policy on the final period.  It runs a few simple,
named evidence-grade controls through the same chronological partitions and
shows all of them.  Exact paid option asks fund entries and exact same-contract
bids fund exits.  The ask/bid pair already pays the displayed spread; separate
stress rows add Tradier passthrough fees, the monthly Pro subscription, and
adverse execution beyond the displayed top of book.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from research.jobs.evaluate_reviewed_allocation_grid import (
    INCONSISTENT,
    PROVEN,
    UNDERPOWERED,
    apply_current_portfolio_policy,
    segment,
)
from research.jobs.evaluate_reviewed_strategy_selector import (
    LAUNCH_PROFIT_FACTOR,
    STRATEGY_SPECS,
    load_reviewed_markouts,
    simulate_policy,
)


DEFAULT_FEE_PER_CONTRACT_PER_SIDE = 0.12
DEFAULT_MONTHLY_SUBSCRIPTION = 10.0

POLICIES: dict[str, frozenset[str]] = {
    "current_all": frozenset(STRATEGY_SPECS),
    "passed_holdout_only": frozenset(PROVEN),
    "passed_plus_underpowered": frozenset((*PROVEN, *UNDERPOWERED)),
    "exclude_inconsistent_two_leg": frozenset(STRATEGY_SPECS) - {
        "V2_TSLA_TWO_LEG_TREND_PULLBACK"
    },
}

STRESS_CASES: dict[str, float] = {
    "quoted_bid_ask": 0.00,
    "one_cent_each_side": 0.01,
    "three_cents_each_side": 0.03,
}


def _strategy_subsets() -> tuple[frozenset[str], ...]:
    """Return every non-empty reviewed-strategy subset in stable order."""
    strategy_ids = tuple(sorted(STRATEGY_SPECS))
    return tuple(
        frozenset(values)
        for size in range(1, len(strategy_ids) + 1)
        for values in combinations(strategy_ids, size)
    )


def _factor(pnls: list[float], fixed_costs: float) -> float | str | None:
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0) + fixed_costs
    if losses <= 0:
        return "inf" if gains > 0 else None
    return round(gains / losses, 4)


def _summary(simulation: dict[str, Any], *, starting_capital: float) -> dict[str, Any]:
    trades = simulation["accepted"]
    pnls = [float(row["pnl"]) for row in trades]
    net_returns = [
        100 * float(row["pnl"]) / float(row["premium_cost"])
        for row in trades if float(row.get("premium_cost") or 0) > 0
    ]
    subscription = float(simulation["cost_model"]["subscription_costs"])
    ending = float(simulation["ending_cash"])
    strategy_rows = {str(row["strategy_id"]) for row in trades}
    return {
        "sizing_model": simulation["sizing_model"],
        "trades": len(trades),
        "wins": sum(value > 0 for value in pnls),
        "win_rate_pct": round(100 * sum(value > 0 for value in pnls) / len(pnls), 2) if pnls else None,
        "net_pnl_after_all_costs": round(ending - starting_capital, 2),
        "ending_cash": round(ending, 2),
        "account_growth_multiple": round(ending / starting_capital, 4),
        "profit_factor_after_all_costs": _factor(pnls, subscription),
        "average_net_trade_return_pct": round(sum(net_returns) / len(net_returns), 4) if net_returns else None,
        "median_net_trade_return_pct": round(median(net_returns), 4) if net_returns else None,
        "cash_cost_basis_max_drawdown_pct": simulation["cost_basis_max_drawdown_pct"],
        "skipped": simulation["skip_counts"],
        "cost_model": simulation["cost_model"],
        "by_strategy": {
            strategy_id: {
                "trades": len(rows),
                "net_pnl": round(sum(float(row["pnl"]) for row in rows), 2),
            }
            for strategy_id in sorted(strategy_rows)
            if (rows := [row for row in trades if str(row["strategy_id"]) == strategy_id])
        },
    }


def _pf_number(value: object) -> float:
    if value == "inf":
        return math.inf
    return float(value or 0)


def _launch_period_gates(summary: dict[str, Any]) -> dict[str, bool]:
    return {
        "at_least_30_trades": summary["trades"] >= 30,
        "net_profitable": summary["net_pnl_after_all_costs"] > 0,
        "positive_median_trade": float(summary["median_net_trade_return_pct"] or 0) > 0,
        "pf_at_least_1_50": (
            _pf_number(summary["profit_factor_after_all_costs"])
            >= LAUNCH_PROFIT_FACTOR
        ),
    }


def _passes_launch_period(summary: dict[str, Any]) -> bool:
    return all(_launch_period_gates(summary).values())


def _run(
    rows: list[dict[str, Any]], *, strategy_ids: frozenset[str],
    starting_capital: float, slippage: float, max_positions: int,
) -> dict[str, Any]:
    candidates = [row for row in rows if row["strategy_id"] in strategy_ids]
    simulation = simulate_policy(
        candidates,
        policy="all_affordable",
        starting_capital=starting_capital,
        allocation_fraction=.15,
        max_positions=max_positions,
        per_contract_fee_per_side=DEFAULT_FEE_PER_CONTRACT_PER_SIDE,
        slippage_price_per_side=slippage,
        monthly_subscription=DEFAULT_MONTHLY_SUBSCRIPTION,
        sizing_model="production_growth_v1",
    )
    summary = _summary(simulation, starting_capital=starting_capital)
    moments = [datetime.fromisoformat(str(row["signal_time"])) for row in candidates]
    summary["candidate_window"] = {
        "start": min(moments).isoformat() if moments else None,
        "end": max(moments).isoformat() if moments else None,
    }
    summary["candidate_counts_by_strategy"] = {
        strategy_id: sum(row["strategy_id"] == strategy_id for row in candidates)
        for strategy_id in sorted(strategy_ids)
    }
    return summary


def build_report(
    rows: list[dict[str, Any]], *, validation_start: date,
    holdout_start: date, starting_capital: float = 5_000.0,
    max_positions: int = 3,
) -> dict[str, Any]:
    routed = apply_current_portfolio_policy(rows)
    periods = {
        "eligibility": segment(routed, None, validation_start),
        "validation": segment(routed, validation_start, holdout_start),
        "holdout": segment(routed, holdout_start, None),
    }
    results: dict[str, Any] = {}
    for policy_name, strategy_ids in POLICIES.items():
        results[policy_name] = {
            stress_name: {
                period_name: _run(
                    period_rows,
                    strategy_ids=strategy_ids,
                    starting_capital=starting_capital,
                    slippage=slippage,
                    max_positions=max_positions,
                )
                for period_name, period_rows in periods.items()
            }
            for stress_name, slippage in STRESS_CASES.items()
        }

    base_case = "one_cent_each_side"
    launch_gates: dict[str, Any] = {}
    for policy_name, policy_results in results.items():
        chronological = policy_results[base_case]
        period_gates = {
            period_name: _launch_period_gates(summary)
            for period_name, summary in chronological.items()
        }
        launch_gates[policy_name] = {
            "stress_case": base_case,
            "periods": period_gates,
            "passed_all_periods": all(
                all(gates.values()) for gates in period_gates.values()
            ),
        }

    # Evaluate all 31 combinations in one pass, but freeze selection using the
    # eligibility period alone.  Validation and holdout may confirm or reject
    # that frozen choice; they can never choose a different subset.  This
    # replaces repeated hand-run leave-one-out studies without turning the
    # final period into a tuning set.
    subset_candidates: list[dict[str, Any]] = []
    for strategy_ids in _strategy_subsets():
        summaries = {
            period_name: _run(
                period_rows,
                strategy_ids=strategy_ids,
                starting_capital=starting_capital,
                slippage=STRESS_CASES[base_case],
                max_positions=max_positions,
            )
            for period_name, period_rows in periods.items()
        }
        eligibility = summaries["eligibility"]
        subset_candidates.append({
            "strategy_ids": sorted(strategy_ids),
            "eligibility_passed": _passes_launch_period(eligibility),
            "summaries": summaries,
            "gates": {
                period_name: _launch_period_gates(summary)
                for period_name, summary in summaries.items()
            },
        })
    selectable = [row for row in subset_candidates if row["eligibility_passed"]]
    selected_subset = max(
        selectable,
        key=lambda row: (
            _pf_number(row["summaries"]["eligibility"]["profit_factor_after_all_costs"]),
            row["summaries"]["eligibility"]["net_pnl_after_all_costs"],
            row["summaries"]["eligibility"]["trades"],
            -len(row["strategy_ids"]),
        ),
        default=None,
    )
    subset_passed = bool(
        selected_subset
        and all(
            all(gates.values())
            for gates in selected_subset["gates"].values()
        )
    )
    exhaustive_subset_screen = {
        "candidate_count": len(subset_candidates),
        "selection_basis": (
            "All non-empty subsets are scored together; choose only among subsets that clear "
            "the 30-trade, net-profit, positive-median, and PF >= 1.50 gates in the eligibility "
            "period. Rank by eligibility PF, then P&L, trades, and fewer strategies. Validation "
            "and holdout may reject but cannot select or replace the frozen subset."
        ),
        "stress_case": base_case,
        "candidates": subset_candidates,
        "selected": selected_subset,
        "passed_all_periods": subset_passed,
        "runtime_changed": False,
    }

    full_growth = {
        policy_name: _run(
            routed,
            strategy_ids=strategy_ids,
            starting_capital=starting_capital,
            slippage=STRESS_CASES[base_case],
            max_positions=max_positions,
        )
        for policy_name, strategy_ids in POLICIES.items()
    }
    passing = [
        policy for policy, gates in launch_gates.items()
        if gates["passed_all_periods"]
    ]
    any_policy_passed = bool(passing or subset_passed)
    return {
        "purpose": "Truthful launch-readiness audit for PF >= 1.50 and growth from $5,000 toward $100,000.",
        "complete": True,
        "starting_capital": starting_capital,
        "target_capital": 100_000.0,
        "required_growth_multiple": round(100_000.0 / starting_capital, 2),
        "growth_comparison_warning": "Policy histories have different start dates because the purchased TSLA archive begins in 2025 while reviewed SPY option evidence begins in May 2026. Compare PF and chronology; do not compare ending balances as equal-duration returns.",
        "validation_start": validation_start.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "strategy_groups": {
            "passed_declared_holdout": list(PROVEN),
            "promising_underpowered": list(UNDERPOWERED),
            "promising_inconsistent": list(INCONSISTENT),
        },
        "policies": {key: sorted(value) for key, value in POLICIES.items()},
        "cost_assumptions": {
            "entry": "Exact paid option ask after the signal.",
            "exit": "Exact same-contract paid option bid at the reviewed exit.",
            "displayed_spread": "Already paid by crossing ask at entry and bid at exit.",
            "passthrough_fee_per_contract_per_side": DEFAULT_FEE_PER_CONTRACT_PER_SIDE,
            "passthrough_fee_basis": "Conservative rounded stress above the currently published clearing/ORF/TAF/CAT components; actual assessment can vary.",
            "tradier_pro_monthly_subscription": DEFAULT_MONTHLY_SUBSCRIPTION,
            "slippage_price_per_side_by_case": STRESS_CASES,
            "position_sizing": "Current production growth-mode ladder: 5%/3%/2%/1% risk tiers, 20% stop-risk denominator, 5% adverse sizing ceiling, tiered notional caps, whole contracts, and the sub-$5k two-contract floor when affordable.",
            "maximum_concurrent_positions": max_positions,
        },
        "period_candidate_counts": {name: len(value) for name, value in periods.items()},
        "results": results,
        "launch_gates": launch_gates,
        "exhaustive_subset_screen": exhaustive_subset_screen,
        "full_history_growth_diagnostic": full_growth,
        "decision": {
            "passed": any_policy_passed,
            "passing_policies": passing,
            "selected_subset_passed": subset_passed,
            "runtime_changed": False,
            "reason": (
                "At least one frozen policy cleared PF, sample, median, and net-profit gates in every chronological period. It still requires new prospective confirmation because the eligibility period selected it from this archive."
                if any_policy_passed else
                "No named policy or eligibility-selected strategy subset cleared the net PF 1.50, sample, median, and profitability gates in every chronological period. Do not represent the bot as launch-ready or project the observed path to $100,000."
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
    parser.add_argument("--starting-capital", type=float, default=5_000.0)
    parser.add_argument("--max-positions", type=int, default=3)
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
        max_positions=args.max_positions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "launch_gates": report["launch_gates"],
        "growth": report["full_history_growth_diagnostic"],
        "decision": report["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
