#!/usr/bin/env python3
"""Evaluate a causal selector across every reviewed paid-option strategy.

The selector is intentionally research-only.  It updates a strategy's
trailing score only after that historical setup's recorded exit, so a later
option return can never influence an earlier routing decision.  All fills use
the already-recorded executable ask and bid for the same contract.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Literal


Policy = Literal["all_affordable", "causal_trailing_quality"]
SizingModel = Literal["allocation", "production_growth_v1"]
LAUNCH_PROFIT_FACTOR = 1.50

STRATEGY_SPECS: dict[str, dict[str, Any]] = {
    "V2_SPY_FAILED_RANGE_RECOVERY": {
        "ticker": "SPY",
        "grade": "passed_declared_holdout",
        "path": ("markouts_by_variant", "sensitive_recovery"),
    },
    "V2_SPY_TREND_CONT": {
        "ticker": "SPY",
        "grade": "passed_declared_holdout",
        "path": ("markouts_by_hold", "30"),
    },
    "V2_SPY_AFTERNOON_FVG": {
        "ticker": "SPY",
        "grade": "promising_underpowered",
        "path": ("portfolio_markouts_by_variant_hold", "live_baseline_0_50_atr", "30"),
    },
    "V2_ORB_PULLBACK": {
        "ticker": "TSLA",
        "grade": "promising_inconsistent",
        "path": ("markouts",),
    },
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": {
        "ticker": "TSLA",
        "grade": "promising_inconsistent",
        "path": ("markouts_by_variant_hold", "baseline", "90"),
    },
}

GRADE_PRIORITY = {
    "passed_declared_holdout": 0,
    "promising_underpowered": 1,
    "promising_inconsistent": 2,
}


def _moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _nested(payload: object, path: Iterable[str]) -> object:
    value = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"missing report path: {'.'.join(path)}")
        value = value[key]
    return value


def _profit_factor(values: Iterable[float]) -> float | None:
    numbers = list(values)
    gains = sum(value for value in numbers if value > 0)
    losses = -sum(value for value in numbers if value < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def load_source(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    """Load one exact reviewed markout set and attach routing metadata."""
    spec = STRATEGY_SPECS[strategy_id]
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = _nested(payload, spec["path"])
    if not isinstance(rows, list):
        raise ValueError(f"{path} requested markout path is not a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        required = ("signal_time", "entry_time", "exit_time", "entry_ask", "exit_bid", "return_pct")
        if any(row.get(field) is None for field in required):
            continue
        normalized.append({
            **row,
            "strategy_id": strategy_id,
            "ticker": spec["ticker"],
            "evidence_grade": spec["grade"],
        })
    return normalized


def load_reviewed_markouts(paths: dict[str, Path]) -> list[dict[str, Any]]:
    missing = set(STRATEGY_SPECS) - set(paths)
    if missing:
        raise ValueError(f"missing strategy reports: {', '.join(sorted(missing))}")
    return [row for strategy_id in STRATEGY_SPECS for row in load_source(paths[strategy_id], strategy_id)]


@dataclass
class OpenTrade:
    ticker: str
    strategy_id: str
    exit_time: datetime
    cost: float
    proceeds: float


def _quality_decision(
    completed_returns: list[float], *, minimum_history: int, trailing_window: int,
) -> tuple[bool, dict[str, Any]]:
    trailing = completed_returns[-trailing_window:]
    if len(trailing) < minimum_history:
        return True, {
            "state": "warmup",
            "completed_observations": len(completed_returns),
            "window_observations": len(trailing),
            "median_return_pct": None,
            "profit_factor": None,
        }
    med = median(trailing)
    factor = _profit_factor(trailing)
    passed = med > 0 and factor is not None and factor >= LAUNCH_PROFIT_FACTOR
    return passed, {
        "state": "eligible" if passed else "quality_paused",
        "completed_observations": len(completed_returns),
        "window_observations": len(trailing),
        "median_return_pct": round(med, 4),
        "profit_factor": round(factor, 4) if factor is not None and factor != float("inf") else ("inf" if factor == float("inf") else None),
    }


def _production_growth_quantity(option_ask: float, account_equity: float) -> tuple[int, dict[str, Any]]:
    """Mirror the current live growth-mode whole-contract sizing rules.

    The live router sizes against a 5%-adverse price ceiling and a 20% option
    stop.  Its balance tiers are 5% risk / 45% notional below $5k, 3% / 30%
    through $25k, 2% / 30% through $50k, then 1% / 20%.  Bootstrap also floors
    an affordable order at two contracts.  Keeping this pure makes the replay
    reproducible instead of reading mutable dashboard settings during a run.
    """
    if option_ask <= 0 or account_equity <= 0:
        return 0, {"tier": "invalid"}
    if account_equity < 5_000:
        risk_pct, notional_pct, tier, bootstrap = .05, .45, "bootstrap", True
    elif account_equity < 25_000:
        risk_pct, notional_pct, tier, bootstrap = .03, .30, "growth", False
    elif account_equity < 50_000:
        risk_pct, notional_pct, tier, bootstrap = .02, .30, "transition", False
    else:
        risk_pct, notional_pct, tier, bootstrap = .01, .20, "preservation", False

    sizing_price = option_ask * 1.05
    risk_per_contract = sizing_price * .20 * 100
    quantity = int((account_equity * risk_pct) / risk_per_contract)
    notional_cap = account_equity * notional_pct
    while quantity > 1 and sizing_price * 100 * quantity > notional_cap:
        quantity -= 1
    if bootstrap:
        if quantity < 2 and sizing_price * 100 * 2 <= notional_cap:
            quantity = 2
        elif quantity == 0 and sizing_price * 100 <= notional_cap:
            quantity = 1
    elif quantity == 0 and sizing_price * 100 <= notional_cap:
        quantity = 1
    return max(0, quantity), {
        "tier": tier,
        "risk_pct": risk_pct,
        "notional_cap_pct": notional_pct,
        "stop_pct": .20,
        "sizing_price_slippage_pct": .05,
    }


def simulate_policy(
    candidates: list[dict[str, Any]], *, policy: Policy, starting_capital: float = 5_000.0,
    allocation_fraction: float = .15, max_positions: int = 3, minimum_history: int = 10,
    trailing_window: int = 20, allocation_by_strategy: dict[str, float] | None = None,
    per_contract_fee_per_side: float = 0.0,
    slippage_price_per_side: float = 0.0,
    monthly_subscription: float = 0.0,
    sizing_model: SizingModel = "allocation",
) -> dict[str, Any]:
    """Route candidates without overlap, borrowed cash, or future leakage.

    Every completed candidate is a shadow observation, whether or not it was
    entered.  That is the only way a paused strategy can later recover, and it
    makes explicit the production prerequisite: continue recording the same
    deterministic contract for all reviewed setup candidates.
    """
    if starting_capital <= 0 or not 0 < allocation_fraction <= 1 or max_positions < 1:
        raise ValueError("capital, allocation fraction, and max positions must be positive")
    if allocation_by_strategy and any(not 0 < float(value) <= 1 for value in allocation_by_strategy.values()):
        raise ValueError("every strategy allocation fraction must be between zero and one")
    if minimum_history < 1 or trailing_window < minimum_history:
        raise ValueError("trailing window must be at least the minimum history")
    if per_contract_fee_per_side < 0 or slippage_price_per_side < 0 or monthly_subscription < 0:
        raise ValueError("fees, slippage, and subscription costs cannot be negative")
    if sizing_model not in {"allocation", "production_growth_v1"}:
        raise ValueError("unsupported sizing model")

    ordered = sorted(candidates, key=lambda row: (
        _moment(row["entry_time"]),
        GRADE_PRIORITY.get(str(row.get("evidence_grade")), 99),
        str(row.get("strategy_id")),
        str(row.get("signal_time")),
    ))
    cash = starting_capital
    peak_equity = starting_capital
    max_drawdown_pct = 0.0
    open_trades: list[OpenTrade] = []
    pending_observations: list[tuple[datetime, str, float]] = []
    completed: dict[str, list[float]] = defaultdict(list)
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    charged_months: set[str] = set()
    transaction_costs = 0.0
    subscription_costs = 0.0

    def equity_at_cost() -> float:
        return cash + sum(trade.cost for trade in open_trades)

    def update_drawdown() -> None:
        nonlocal peak_equity, max_drawdown_pct
        equity = equity_at_cost()
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak_equity - equity) / peak_equity * 100)

    def release_through(moment: datetime) -> None:
        nonlocal cash, open_trades, pending_observations
        remaining_trades: list[OpenTrade] = []
        for trade in sorted(open_trades, key=lambda item: item.exit_time):
            if trade.exit_time <= moment:
                cash += trade.proceeds
            else:
                remaining_trades.append(trade)
        open_trades = remaining_trades
        remaining_observations: list[tuple[datetime, str, float]] = []
        for exit_time, strategy_id, return_pct in pending_observations:
            if exit_time <= moment:
                completed[strategy_id].append(return_pct)
            else:
                remaining_observations.append((exit_time, strategy_id, return_pct))
        pending_observations = remaining_observations
        update_drawdown()

    for row in ordered:
        entry_time = _moment(row["entry_time"])
        exit_time = _moment(row["exit_time"])
        strategy_id = str(row["strategy_id"])
        ticker = str(row["ticker"])
        release_through(entry_time)
        month = entry_time.strftime("%Y-%m")
        if month not in charged_months:
            cash -= monthly_subscription
            subscription_costs += monthly_subscription
            charged_months.add(month)
            update_drawdown()

        ask = float(row.get("entry_ask") or 0)
        bid = float(row.get("exit_bid") or 0)
        if ask <= 0 or bid < 0:
            skipped.append({**row, "skip_reason": "invalid_quote"})
            continue
        one_contract_entry = ask * 100 + per_contract_fee_per_side + slippage_price_per_side * 100
        one_contract_exit = bid * 100 - per_contract_fee_per_side - slippage_price_per_side * 100
        cost_adjusted_observation_return = 100 * (one_contract_exit - one_contract_entry) / (ask * 100)
        row = {
            **row,
            "cost_adjusted_observation_return_pct": round(cost_adjusted_observation_return, 6),
        }

        # The observation becomes learnable only after its own exit.  Appending
        # it here cannot affect the current decision or any earlier decision.
        # Judge completed evidence after the same friction used in the account
        # simulation; otherwise marginal gross winners train the gate to allow
        # trades that are net losers.
        pending_observations.append((exit_time, strategy_id, cost_adjusted_observation_return))

        quality_allowed, quality = _quality_decision(
            completed[strategy_id], minimum_history=minimum_history, trailing_window=trailing_window,
        )
        if policy == "causal_trailing_quality" and not quality_allowed:
            skipped.append({**row, "skip_reason": "trailing_quality", "quality_at_decision": quality})
            continue
        if any(trade.ticker == ticker for trade in open_trades):
            skipped.append({**row, "skip_reason": "ticker_position_open", "quality_at_decision": quality})
            continue
        if len(open_trades) >= max_positions:
            skipped.append({**row, "skip_reason": "portfolio_slots_full", "quality_at_decision": quality})
            continue
        entry_cost_per_contract = (
            ask * 100 + per_contract_fee_per_side + slippage_price_per_side * 100
        )
        if sizing_model == "production_growth_v1":
            quantity, sizing_detail = _production_growth_quantity(ask, equity_at_cost())
            # A broker cannot spend unavailable settled buying power even when
            # the risk formula permits a larger whole-contract order.
            quantity = min(quantity, int(cash // entry_cost_per_contract))
            strategy_allocation = None
        else:
            strategy_allocation = float(
                (allocation_by_strategy or {}).get(strategy_id, allocation_fraction)
            )
            quantity = int((cash * strategy_allocation) // entry_cost_per_contract)
            sizing_detail = {
                "tier": "fixed_allocation",
                "allocation_fraction": strategy_allocation,
            }
        if quantity < 1:
            skipped.append({**row, "skip_reason": "unaffordable", "quality_at_decision": quality})
            continue
        premium_cost = ask * 100 * quantity
        gross_proceeds = bid * 100 * quantity
        entry_friction = quantity * (
            per_contract_fee_per_side + slippage_price_per_side * 100
        )
        exit_friction = quantity * (
            per_contract_fee_per_side + slippage_price_per_side * 100
        )
        total_cost = premium_cost + entry_friction
        proceeds = gross_proceeds - exit_friction
        transaction_costs += entry_friction + exit_friction
        cash -= total_cost
        # Only the premium remains an asset immediately after entry; fees and
        # adverse execution are realized friction, not recoverable cost basis.
        open_trades.append(OpenTrade(ticker, strategy_id, exit_time, premium_cost, proceeds))
        accepted.append({
            **row,
            "quantity": quantity,
            "cost": round(total_cost, 2),
            "proceeds": round(proceeds, 2),
            "premium_cost": round(premium_cost, 2),
            "gross_proceeds": round(gross_proceeds, 2),
            "transaction_costs": round(entry_friction + exit_friction, 4),
            "pnl": round(proceeds - total_cost, 2),
            "quality_at_decision": quality,
            "allocation_fraction": strategy_allocation,
            "sizing_detail": sizing_detail,
        })
        update_drawdown()

    release_through(datetime.max.replace(tzinfo=_moment(ordered[0]["entry_time"]).tzinfo) if ordered else datetime.max)
    return {
        "policy": policy,
        "sizing_model": sizing_model,
        "allocation_by_strategy": allocation_by_strategy or {},
        "starting_capital": round(starting_capital, 2),
        "ending_cash": round(cash, 2),
        "account_return_pct": round((cash - starting_capital) / starting_capital * 100, 4),
        "cost_basis_max_drawdown_pct": round(max_drawdown_pct, 4),
        "cost_model": {
            "per_contract_fee_per_side": per_contract_fee_per_side,
            "slippage_price_per_side": slippage_price_per_side,
            "monthly_subscription": monthly_subscription,
            "charged_months": sorted(charged_months),
            "transaction_costs": round(transaction_costs, 4),
            "subscription_costs": round(subscription_costs, 2),
        },
        "accepted": accepted,
        "skipped": skipped,
        "skip_counts": dict(Counter(str(row["skip_reason"]) for row in skipped)),
        "completed_shadow_observations": {key: len(value) for key, value in completed.items()},
    }


def summarize_trades(
    rows: list[dict[str, Any]], *, starting_capital: float,
    fixed_costs: float = 0.0,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _moment(row["exit_time"]))
    pnls = [float(row["pnl"]) for row in ordered]
    returns = [
        100 * float(row["pnl"]) / float(row["premium_cost"])
        for row in ordered if float(row.get("premium_cost") or 0) > 0
    ]
    cumulative = -fixed_costs
    peak = 0.0
    max_drawdown = fixed_costs
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0) + fixed_costs
    factor = None if losses <= 0 and gains <= 0 else (float("inf") if losses <= 0 else gains / losses)
    net_pnl = sum(pnls) - fixed_costs
    return {
        "trades": len(rows),
        "wins": sum(value > 0 for value in pnls),
        "win_rate_pct": round(100 * sum(value > 0 for value in pnls) / len(rows), 2) if rows else None,
        "pnl": round(net_pnl, 2),
        "pnl_contribution_pct_of_starting_capital": round(net_pnl / starting_capital * 100, 4),
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "profit_factor": round(factor, 4) if factor is not None and factor != float("inf") else ("inf" if factor == float("inf") else None),
        "realized_pnl_max_drawdown": round(max_drawdown, 2),
        "fixed_costs": round(fixed_costs, 2),
        "by_strategy": {
            strategy_id: {
                "trades": len(strategy_rows),
                "pnl": round(sum(float(row["pnl"]) for row in strategy_rows), 2),
                "average_return_pct": round(sum(float(row["return_pct"]) for row in strategy_rows) / len(strategy_rows), 4),
            }
            for strategy_id in sorted({str(row["strategy_id"]) for row in rows})
            if (strategy_rows := [row for row in rows if str(row["strategy_id"]) == strategy_id])
        },
    }


def build_report(
    candidates: list[dict[str, Any]], *, holdout_start: date, starting_capital: float = 5_000.0,
    allocation_fraction: float = .15, max_positions: int = 2, minimum_history: int = 10,
    trailing_window: int = 20,
    per_contract_fee_per_side: float = .12,
    slippage_price_per_side: float = .01,
    monthly_subscription: float = 10.0,
    sizing_model: SizingModel = "production_growth_v1",
) -> dict[str, Any]:
    simulations = {
        policy: simulate_policy(
            candidates,
            policy=policy,
            starting_capital=starting_capital,
            allocation_fraction=allocation_fraction,
            max_positions=max_positions,
            minimum_history=minimum_history,
            trailing_window=trailing_window,
            per_contract_fee_per_side=per_contract_fee_per_side,
            slippage_price_per_side=slippage_price_per_side,
            monthly_subscription=monthly_subscription,
            sizing_model=sizing_model,
        )
        for policy in ("all_affordable", "causal_trailing_quality")
    }
    for result in simulations.values():
        accepted = result.pop("accepted")
        skipped = result.pop("skipped")
        charged_months = [date.fromisoformat(f"{month}-01") for month in result["cost_model"]["charged_months"]]
        training_fixed = monthly_subscription * sum(month < holdout_start for month in charged_months)
        holdout_fixed = monthly_subscription * sum(month >= holdout_start for month in charged_months)
        result["segments"] = {
            "training": summarize_trades(
                [row for row in accepted if _moment(row["signal_time"]).date() < holdout_start],
                starting_capital=starting_capital,
                fixed_costs=training_fixed,
            ),
            "holdout": summarize_trades(
                [row for row in accepted if _moment(row["signal_time"]).date() >= holdout_start],
                starting_capital=starting_capital,
                fixed_costs=holdout_fixed,
            ),
        }
        result["accepted_trades"] = accepted
        result["skipped_decisions"] = skipped

    baseline = simulations["all_affordable"]["segments"]["holdout"]
    causal = simulations["causal_trailing_quality"]["segments"]["holdout"]
    protected_strategy_ids = sorted(
        strategy_id for strategy_id, spec in STRATEGY_SPECS.items()
        if spec.get("grade") == "passed_declared_holdout"
    )
    protected_contribution_gates = {
        strategy_id: bool(
            (detail := causal.get("by_strategy", {}).get(strategy_id))
            and detail.get("trades", 0) > 0
            and float(detail.get("pnl", 0)) > 0
            and float(detail.get("average_return_pct", 0)) > 0
        )
        for strategy_id in protected_strategy_ids
    }
    causal_factor = causal["profit_factor"]
    factor_pass = causal_factor == "inf" or (
        isinstance(causal_factor, (int, float))
        and causal_factor >= LAUNCH_PROFIT_FACTOR
    )
    retained_enough = causal["trades"] >= max(10, int(baseline["trades"] * .5))
    improved = (
        causal["pnl"] >= baseline["pnl"]
        or causal["realized_pnl_max_drawdown"] < baseline["realized_pnl_max_drawdown"]
    )
    passed = bool(
        retained_enough
        and causal["pnl"] > 0
        and causal["average_return_pct"] is not None
        and causal["average_return_pct"] > 0
        and factor_pass
        and improved
        and all(protected_contribution_gates.values())
    )
    return {
        "purpose": "Causal combined selector for all five reviewed paid-option strategy candidates; research-only.",
        "complete": True,
        "candidate_markouts": len(candidates),
        "holdout_start": holdout_start.isoformat(),
        "predeclared_rule": {
            "warmup_completed_observations": minimum_history,
            "trailing_completed_observations": trailing_window,
            "allow_when": f"trailing median option return > 0 and trailing option P&L profit factor >= {LAUNCH_PROFIT_FACTOR:.2f}",
            "causality": "A candidate return enters history only after its recorded exit timestamp.",
            "shadow_requirement": "Production must keep measuring deterministic contract markouts for every reviewed setup, including non-entered setups.",
            "portfolio": (
                f"One open position per ticker, at most {max_positions} total, "
                + (
                    "the current production growth-mode risk ladder."
                    if sizing_model == "production_growth_v1"
                    else f"{allocation_fraction:.0%} of available cash per position."
                )
            ),
        },
        "execution_scope": (
            "Recorded paid option ask entry and same-contract bid exit; whole contracts; "
            f"${per_contract_fee_per_side:.2f}/contract/side, ${slippage_price_per_side:.2f} "
            f"option-price slippage/side, ${monthly_subscription:.2f}/month, sizing={sizing_model}. "
            "No intratrade quote path."
        ),
        "simulations": simulations,
        "decision": {
            "passed": passed,
            "selected_policy": "causal_trailing_quality" if passed else "all_affordable",
            "protected_strategy_contribution_gates": protected_contribution_gates,
            "reason": (
                f"Causal filter kept sufficient later trades, positive expectancy/P&L and PF >= {LAUNCH_PROFIT_FACTOR:.2f}, while improving later P&L or realized-P&L drawdown."
                if passed else
                "Causal filter did not clear every later-data, retention, and protected-strategy contribution gate; keep the reviewed strategies independent."
            ),
            "runtime_changed": False,
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
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--starting-capital", type=float, default=5_000.0)
    parser.add_argument("--allocation-fraction", type=float, default=.15)
    parser.add_argument("--max-positions", type=int, default=2)
    parser.add_argument("--minimum-history", type=int, default=10)
    parser.add_argument("--trailing-window", type=int, default=20)
    parser.add_argument("--per-contract-fee-per-side", type=float, default=.12)
    parser.add_argument("--slippage-price-per-side", type=float, default=.01)
    parser.add_argument("--monthly-subscription", type=float, default=10.0)
    parser.add_argument(
        "--sizing-model", choices=("allocation", "production_growth_v1"),
        default="production_growth_v1",
    )
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
        holdout_start=args.holdout_start,
        starting_capital=args.starting_capital,
        allocation_fraction=args.allocation_fraction,
        max_positions=args.max_positions,
        minimum_history=args.minimum_history,
        trailing_window=args.trailing_window,
        per_contract_fee_per_side=args.per_contract_fee_per_side,
        slippage_price_per_side=args.slippage_price_per_side,
        monthly_subscription=args.monthly_subscription,
        sizing_model=args.sizing_model,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_markouts": report["candidate_markouts"],
        "decision": report["decision"],
        "holdout": {
            key: value["segments"]["holdout"]
            for key, value in report["simulations"].items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
