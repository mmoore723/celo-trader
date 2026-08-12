#!/usr/bin/env python3
"""Compare paid option markouts as one constrained TSLA paper portfolio.

This is deliberately separate from per-signal studies.  It never uses a
trade's future option return to decide whether it gets a slot.  Instead it
applies predeclared, observable routing policies when two strategy signals
overlap, then selects a policy on the earlier segment and reports its later
segment unchanged.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _load(path: Path, strategy: str, context: str | None) -> list[dict[str, Any]]:
    report = json.loads(path.read_text())
    rows = report.get("markouts_by_context", {}).get(context, []) if context else report.get("markouts", [])
    if not isinstance(rows, list):
        raise ValueError(f"{path} does not contain the requested markouts")
    return [{**row, "strategy": strategy} for row in rows]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize independent option markouts without inventing an account curve.

    Each record is a one-contract percentage return from the source study.
    Adding those percentages is sometimes a handy diagnostic, but it is not a
    compounded portfolio return: trade notionals, sizing, and overlapping
    capital are intentionally outside this narrow slot-allocation test.
    """
    returns = [float(row["return_pct"]) for row in rows]
    wins = sum(value > 0 for value in returns)
    return {
        "trades": len(rows),
        "wins": wins,
        "win_rate_pct": round(100 * wins / len(rows), 2) if rows else None,
        "average_return_pct": round(sum(returns) / len(rows), 4) if rows else None,
        "sum_of_independent_trade_returns_pct": round(sum(returns), 4),
        "portfolio_return_available": False,
    }


def _account_summary(
    rows: list[dict[str, Any]], *, starting_capital: float, allocation_fraction: float,
) -> dict[str, Any]:
    """Model cash conservatively for already-routed, real option markouts.

    The paid markouts contain an executable ask and bid for the same contract.
    At entry, this model spends up to ``allocation_fraction`` of the currently
    available cash on whole option contracts; it releases the sale proceeds at
    the recorded bid exit.  It does not use a favorable midpoint, borrowed
    cash, or any later information to choose a trade.
    """
    cash = starting_capital
    high_water = cash
    max_drawdown_pct = 0.0
    held: list[tuple[datetime, float, float]] = []  # exit time, cost, proceeds
    entered = 0
    skipped_unaffordable = 0

    def release_through(moment: datetime) -> None:
        nonlocal cash, high_water, max_drawdown_pct
        remaining: list[tuple[datetime, float, float]] = []
        for exit_time, _cost, proceeds in held:
            if exit_time <= moment:
                cash += proceeds
            else:
                remaining.append((exit_time, _cost, proceeds))
        held[:] = remaining
        # Mark-to-market is deliberately avoided: only settled executable
        # exits affect the curve, which keeps this conservative and auditable.
        high_water = max(high_water, cash)
        if high_water > 0:
            max_drawdown_pct = max(max_drawdown_pct, (high_water - cash) / high_water * 100)

    for row in sorted(rows, key=lambda item: (_moment(item["entry_time"]), item["signal_time"])):
        release_through(_moment(row["entry_time"]))
        entry = float(row.get("entry_ask") or 0)
        exit_price = float(row.get("exit_bid") or 0)
        if entry <= 0 or exit_price < 0:
            skipped_unaffordable += 1
            continue
        contract_cost = entry * 100
        budget = cash * allocation_fraction
        quantity = int(budget // contract_cost)
        if quantity < 1:
            skipped_unaffordable += 1
            continue
        cost = contract_cost * quantity
        proceeds = exit_price * 100 * quantity
        cash -= cost
        held.append((_moment(row["exit_time"]), cost, proceeds))
        entered += 1

    # Liquidate the remaining positions only at their actual, already-recorded
    # bid exits; no synthetic end-of-window valuation is introduced.
    for exit_time, _cost, proceeds in sorted(held, key=lambda item: item[0]):
        cash += proceeds
        high_water = max(high_water, cash)
        if high_water > 0:
            max_drawdown_pct = max(max_drawdown_pct, (high_water - cash) / high_water * 100)
    return {
        "starting_capital": round(starting_capital, 2),
        "allocation_fraction_per_position": allocation_fraction,
        "entered_trades": entered,
        "skipped_unaffordable": skipped_unaffordable,
        "ending_cash": round(cash, 2),
        "account_return_pct": round((cash - starting_capital) / starting_capital * 100, 4),
        "settled_cash_max_drawdown_pct": round(max_drawdown_pct, 4),
        "model_scope": "Cash-only, whole-contract model using recorded paid ask entries and bid exits; no commissions or mark-to-market drawdown.",
    }


def _route(
    candidates: list[dict[str, Any]], max_positions: int, priority: tuple[str, ...], *,
    starting_capital: float, allocation_fraction: float,
) -> list[dict[str, Any]]:
    """Accept only entries with both a free slot and an affordable contract.

    A contract that the account cannot buy must not reserve a position slot.
    This mirrors the cash model below and prevents an expensive rejected signal
    from hiding a later, genuinely affordable candidate.
    """
    ranking = {strategy: index for index, strategy in enumerate(priority)}
    ordered = sorted(candidates, key=lambda row: (_moment(row["entry_time"]), ranking.get(row["strategy"], 99), row["signal_time"]))
    cash = starting_capital
    open_positions: list[tuple[datetime, float]] = []  # exit time, proceeds
    accepted: list[dict[str, Any]] = []
    for row in ordered:
        entry = _moment(row["entry_time"])
        remaining: list[tuple[datetime, float]] = []
        for exit_time, proceeds in open_positions:
            if exit_time <= entry:
                cash += proceeds
            else:
                remaining.append((exit_time, proceeds))
        open_positions = remaining
        if len(open_positions) >= max_positions:
            continue
        ask = float(row.get("entry_ask") or 0)
        bid = float(row.get("exit_bid") or 0)
        if ask <= 0 or bid < 0:
            continue
        quantity = int((cash * allocation_fraction) // (ask * 100))
        if quantity < 1:
            continue
        accepted.append(row)
        cash -= ask * 100 * quantity
        open_positions.append((_moment(row["exit_time"]), bid * 100 * quantity))
    return accepted


def _segments(
    rows: list[dict[str, Any]], cutoff: date, *, starting_capital: float, allocation_fraction: float,
) -> dict[str, Any]:
    training = [row for row in rows if _moment(row["signal_time"]).date() < cutoff]
    holdout = [row for row in rows if _moment(row["signal_time"]).date() >= cutoff]
    return {
        "all": {"trade_markouts": _summary(rows), "cash_model": _account_summary(rows, starting_capital=starting_capital, allocation_fraction=allocation_fraction)},
        "training": {"trade_markouts": _summary(training), "cash_model": _account_summary(training, starting_capital=starting_capital, allocation_fraction=allocation_fraction)},
        "holdout": {"trade_markouts": _summary(holdout), "cash_model": _account_summary(holdout, starting_capital=starting_capital, allocation_fraction=allocation_fraction)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orb", type=Path, required=True, help="Paid ORB report with markouts")
    parser.add_argument("--trend", type=Path, required=True, help="Paid Trend context report")
    parser.add_argument("--trend-context", required=True, help="Predeclared Trend context name")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 5, 19))
    parser.add_argument("--max-positions", type=int, default=2)
    parser.add_argument("--starting-capital", type=float, default=5_000.0)
    parser.add_argument("--allocation-fraction", type=float, default=.15,
                        help="Maximum fraction of available cash allocated to a single position.")
    args = parser.parse_args()
    if args.max_positions < 1 or args.starting_capital <= 0 or not 0 < args.allocation_fraction <= 1:
        parser.error("positions, starting capital, and allocation fraction must be positive")

    candidates = _load(args.orb, "v2_orb_pullback", None) + _load(args.trend, "v2_trend_continuation", args.trend_context)
    # These are the only policy alternatives. They differ only by the
    # observable strategy identity when entries are simultaneous.
    policies = {
        "orb_priority": ("v2_orb_pullback", "v2_trend_continuation"),
        "trend_priority": ("v2_trend_continuation", "v2_orb_pullback"),
    }
    outcomes = {name: _segments(
                    _route(
                        candidates, args.max_positions, priority,
                        starting_capital=args.starting_capital,
                        allocation_fraction=args.allocation_fraction,
                    ), args.holdout_start,
                    starting_capital=args.starting_capital, allocation_fraction=args.allocation_fraction,
                )
                for name, priority in policies.items()}
    eligible = [name for name, value in outcomes.items() if value["training"]["trade_markouts"]["trades"] >= 20]
    selected = max(
        eligible,
        key=lambda name: (
            outcomes[name]["training"]["cash_model"]["account_return_pct"],
            outcomes[name]["training"]["trade_markouts"]["trades"],
        ),
    ) if eligible else None
    result = {
        "purpose": "Paid TSLA combined-strategy slot-allocation comparison; research-only.",
        "execution": "Uses observed option ask entry and bid exit from the source studies. No future return is used to route an entry.",
        "metric_scope": (
            "Slot allocation is selected from earlier data only. The cash model uses whole contracts, paid ask entries, "
            "and paid bid exits, but does not include commissions or intratrade mark-to-market equity."
        ),
        "orb_report": str(args.orb), "trend_report": str(args.trend), "trend_context": args.trend_context,
        "holdout_start": args.holdout_start.isoformat(), "max_positions": args.max_positions,
        "starting_capital": args.starting_capital, "allocation_fraction": args.allocation_fraction,
        "candidate_markouts": len(candidates), "policies": outcomes,
        "selection": {
            "selected_policy": selected,
            "rule": "highest earlier cash-model account return; ties use more trades",
            "holdout": outcomes[selected]["holdout"] if selected else None,
            "passed": bool(
                selected
                and outcomes[selected]["holdout"]["trade_markouts"]["trades"] >= 10
                and outcomes[selected]["holdout"]["cash_model"]["account_return_pct"] > 0
            ),
        },
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["selection"], indent=2))


if __name__ == "__main__":
    main()
