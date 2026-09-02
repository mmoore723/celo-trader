#!/usr/bin/env python3
"""Three-period fixed-hold decision for SPY Failed-Range Recovery.

The production audit suggested that this mean-reversion entry often gives
back its early gain.  That observation is only a hypothesis: this assessor
uses May to select one of the predeclared 5/10/15-minute clocks, then requires
the same clock to beat the 30-minute control in June and July.  It reads a
completed paid-quote study and cannot change production settings or place an
order.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.jobs.compare_paid_orb_exits import non_overlapping_positions


CONTROL = 30
CANDIDATES = (5, 10, 15)
PERIODS = {
    "training_may": (date(2026, 5, 1), date(2026, 6, 1)),
    "validation_june": (date(2026, 6, 1), date(2026, 7, 1)),
    "holdout_july": (date(2026, 7, 1), date(2026, 8, 1)),
}
MINIMUM_TRADES = {"training_may": 4, "validation_june": 5, "holdout_july": 7}
ROUND_TRIP_COST = 0.70
MINIMUM_PROFIT_FACTOR = 1.50


def period_rows(rows: list[dict[str, object]], start: date, end: date) -> list[dict[str, object]]:
    return [
        row for row in rows
        if start <= datetime.fromisoformat(str(row["signal_time"])).date() < end
    ]


def metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    """Report one-contract economics after the declared per-contract fees."""
    pnls = [
        (float(row["exit_bid"]) - float(row["entry_ask"])) * 100.0 - ROUND_TRIP_COST
        for row in rows
    ]
    if not pnls:
        return {
            "trades": 0, "net_pnl_one_contract": 0.0, "average_pnl_one_contract": None,
            "win_rate_pct": None, "profit_factor": None, "max_drawdown_one_contract": 0.0,
        }
    gains = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    equity = peak = drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    loss_total = -sum(losses)
    return {
        "trades": len(pnls),
        "net_pnl_one_contract": round(sum(pnls), 2),
        "average_pnl_one_contract": round(sum(pnls) / len(pnls), 2),
        "win_rate_pct": round(len(gains) / len(pnls) * 100.0, 2),
        "profit_factor": round(sum(gains) / loss_total, 4) if loss_total else None,
        "max_drawdown_one_contract": round(drawdown, 2),
    }


def _profit_factor(value: object) -> float:
    return float("inf") if value is None else float(value)


def gate(candidate: dict[str, object], control: dict[str, object], minimum: int) -> dict[str, object]:
    candidate_trades, control_trades = int(candidate["trades"]), int(control["trades"])
    coverage = candidate_trades / control_trades if control_trades else 0.0
    checks = {
        "minimum_trades": candidate_trades >= minimum,
        "at_least_80pct_control_coverage": coverage >= 0.80,
        "positive_net_pnl": float(candidate["net_pnl_one_contract"]) > 0.0,
        "profit_factor_at_least_1_50": _profit_factor(candidate["profit_factor"]) >= MINIMUM_PROFIT_FACTOR,
        "net_pnl_beats_fixed_30m": (
            float(candidate["net_pnl_one_contract"]) > float(control["net_pnl_one_contract"])
        ),
        "profit_factor_not_worse_than_fixed_30m": (
            _profit_factor(candidate["profit_factor"]) >= _profit_factor(control["profit_factor"])
        ),
        "drawdown_no_more_than_110pct_fixed_30m": (
            float(candidate["max_drawdown_one_contract"])
            <= max(0.01, float(control["max_drawdown_one_contract"]) * 1.10)
        ),
    }
    return {
        "passed": all(checks.values()),
        "coverage_vs_control_pct": round(coverage * 100.0, 2),
        "checks": checks,
    }


def assess(payload: dict[str, object]) -> dict[str, object]:
    if not payload.get("complete"):
        raise ValueError("input study is incomplete")
    raw = payload.get("markouts_by_hold")
    if not isinstance(raw, dict) or any(str(hold) not in raw for hold in (*CANDIDATES, CONTROL)):
        raise ValueError("input study is missing a predeclared fixed hold")
    portfolios = {
        hold: non_overlapping_positions(list(raw[str(hold)]))
        for hold in (*CANDIDATES, CONTROL)
    }
    summaries = {
        period: {
            str(hold): metrics(period_rows(rows, start, end))
            for hold, rows in portfolios.items()
        }
        for period, (start, end) in PERIODS.items()
    }
    training_gates = {
        str(hold): gate(
            summaries["training_may"][str(hold)],
            summaries["training_may"][str(CONTROL)],
            MINIMUM_TRADES["training_may"],
        )
        for hold in CANDIDATES
    }
    eligible = [hold for hold in CANDIDATES if training_gates[str(hold)]["passed"]]
    selected = max(
        eligible,
        key=lambda hold: (
            float(summaries["training_may"][str(hold)]["net_pnl_one_contract"]),
            -float(summaries["training_may"][str(hold)]["max_drawdown_one_contract"]),
            -CANDIDATES.index(hold),
        ),
    ) if eligible else None
    later_gates: dict[str, object] = {}
    if selected is not None:
        for period in ("validation_june", "holdout_july"):
            later_gates[period] = gate(
                summaries[period][str(selected)],
                summaries[period][str(CONTROL)],
                MINIMUM_TRADES[period],
            )
    promote = bool(selected is not None and all(item["passed"] for item in later_gates.values()))
    return {
        "decision": "promote_fixed_hold" if promote else "retain_fixed_30m",
        "selected_hold_minutes": selected,
        "round_trip_cost_per_contract": ROUND_TRIP_COST,
        "minimum_profit_factor_each_period": MINIMUM_PROFIT_FACTOR,
        "selection_protocol": (
            "A 5/10/15-minute hold must pass every May gate; choose the highest May net P&L, "
            "then lower drawdown, then declared order."
        ),
        "promotion_protocol": (
            "The one May-selected hold must independently pass the same coverage, cost-adjusted "
            "PF >= 1.50, P&L, and drawdown gates in June and July."
        ),
        "periods": {name: [start.isoformat(), end.isoformat()] for name, (start, end) in PERIODS.items()},
        "minimum_trades": MINIMUM_TRADES,
        "summaries": summaries,
        "training_gates": training_gates,
        "later_gates": later_gates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "purpose": "Causal three-period SPY Failed-Range Recovery fixed-hold decision.",
        "source_study": str(args.input),
        "assessment": assess(json.loads(args.input.read_text(encoding="utf-8"))),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": report["assessment"]["decision"],
        "selected_hold_minutes": report["assessment"]["selected_hold_minutes"],
    }, indent=2))


if __name__ == "__main__":
    main()
