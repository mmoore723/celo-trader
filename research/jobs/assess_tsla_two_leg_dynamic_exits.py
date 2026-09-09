"""Chronological selection and untouched holdout for Two-Leg exits."""
from __future__ import annotations

from datetime import date, datetime
import statistics
from typing import Iterable, Sequence

from research.engine.two_leg_dynamic_exits import RULES


def comparable_rows(rows_by_rule: dict[str, list[dict[str, object]]]) -> dict[str, list[dict[str, object]]]:
    ids = [{str(row["signal_time"]) for row in rows} for rows in rows_by_rule.values()]
    common = set.intersection(*ids) if ids else set()
    return {rule: [row for row in rows if str(row["signal_time"]) in common]
            for rule, rows in rows_by_rule.items()}


def summarize(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(rows, key=lambda row: str(row["signal_time"]))
    pnl = [float(row["net_pnl_one_contract"]) for row in ordered]
    returns = [float(row["net_return_pct"]) for row in ordered]
    gains, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    factor: float | str | None = round(gains / losses, 4) if losses else ("inf" if gains else None)
    equity = peak = drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "results": len(pnl), "wins": sum(x > 0 for x in pnl),
        "win_rate_pct": round(100 * sum(x > 0 for x in pnl) / len(pnl), 2) if pnl else None,
        "profit_factor": factor, "net_pnl_one_contract": round(sum(pnl), 2),
        "average_net_return_pct": round(statistics.mean(returns), 4) if returns else None,
        "median_net_return_pct": round(statistics.median(returns), 4) if returns else None,
        "max_drawdown_one_contract": round(drawdown, 2),
    }


def assess(
    rows_by_rule: dict[str, list[dict[str, object]]], holdout_start: date, *,
    minimum_training: int = 30, minimum_holdout: int = 10,
) -> dict[str, object]:
    """Select only on earlier rows, then judge once on untouched later rows."""
    comparable = comparable_rows(rows_by_rule)
    periods: dict[str, dict[str, dict[str, object]]] = {}
    for rule, rows in comparable.items():
        training = [row for row in rows if _day(row) < holdout_start]
        holdout = [row for row in rows if _day(row) >= holdout_start]
        periods[rule] = {"training": summarize(training), "holdout": summarize(holdout),
                         "all": summarize(rows)}
    control = periods["fixed_90m"]["training"]
    eligible = [
        rule for rule in RULES[1:]
        if _passes(periods[rule]["training"], minimum_training, control)
    ]
    selected = max(eligible, key=lambda rule: _rank(periods[rule]["training"])) if eligible else None
    holdout_passed = False
    if selected:
        holdout_passed = _passes(
            periods[selected]["holdout"], minimum_holdout,
            periods["fixed_90m"]["holdout"],
        )
    return {
        "comparison_universe": "same signals with an executable bid under every exit",
        "holdout_start": holdout_start.isoformat(),
        "training_gate": f">={minimum_training} results, PF >=1.5, positive median/P&L, max drawdown no worse than fixed 90m",
        "holdout_gate": f">={minimum_holdout} results with the same quality gates; never used for selection",
        "selected_on_training": selected, "holdout_passed": holdout_passed,
        "decision": (
            "research_candidate_only; requires fresh forward proof before any paper/live change"
            if selected and holdout_passed else
            "no dynamic exit passed this family; preserve the strategy and test a different exit family"
        ),
        "summaries": periods,
    }


def _day(row: dict[str, object]) -> date:
    return datetime.fromisoformat(str(row["signal_time"])).date()


def _numeric_pf(summary: dict[str, object]) -> float:
    value = summary["profit_factor"]
    return float("inf") if value == "inf" else float(value or 0.0)


def _passes(summary: dict[str, object], minimum: int, control: dict[str, object]) -> bool:
    return (
        int(summary["results"]) >= minimum and _numeric_pf(summary) >= 1.5
        and float(summary["median_net_return_pct"] or 0) > 0
        and float(summary["net_pnl_one_contract"] or 0) > 0
        and float(summary["max_drawdown_one_contract"] or 0)
        <= float(control["max_drawdown_one_contract"] or 0)
    )


def _rank(summary: dict[str, object]) -> tuple[float, float, float]:
    return (_numeric_pf(summary), float(summary["net_pnl_one_contract"] or 0),
            float(summary["median_net_return_pct"] or 0))
