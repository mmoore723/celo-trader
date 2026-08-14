"""Chronological validation rules for promoting an AI entry opinion.

The model is compared with the exact deterministic strategy it would modify.
Only executable option ask-to-bid outcomes count toward promotion.  This
module recommends a policy state; it never changes production enforcement.
"""

from __future__ import annotations

from math import inf
from statistics import mean
from typing import Any, Iterable


MIN_OPTION_EPISODES = 60
MIN_TRADING_DAYS = 20
MIN_ACTION_EPISODES = 12
MIN_HOLDOUT_EPISODES = 12
MIN_HOLDOUT_DAYS = 5
MIN_HOLDOUT_PROFIT_FACTOR = 1.05


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if not values:
        return None
    if losses == 0:
        return inf if gains > 0 else None
    return gains / losses


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = [float(row["baseline_return_pct"]) for row in rows]
    policy = [float(row["policy_return_pct"]) for row in rows]
    baseline_avg = mean(baseline) if baseline else None
    policy_avg = mean(policy) if policy else None
    return {
        "episodes": len(rows),
        "days": len({str(row.get("observed_at") or "")[:10] for row in rows}),
        "baseline_avg_return_pct": round(baseline_avg, 4) if baseline_avg is not None else None,
        "ai_policy_avg_return_pct": round(policy_avg, 4) if policy_avg is not None else None,
        "incremental_avg_return_pct": round(policy_avg - baseline_avg, 4) if baseline_avg is not None else None,
        "baseline_profit_factor": round(value, 3) if (value := _profit_factor(baseline)) not in (None, inf) else ("infinite" if value == inf else None),
        "ai_policy_profit_factor": round(value, 3) if (value := _profit_factor(policy)) not in (None, inf) else ("infinite" if value == inf else None),
    }


def evaluate_ai_gate_policy(episodes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return an auditable promotion recommendation from independent episodes."""
    rows = sorted(
        (dict(row) for row in episodes if row.get("baseline_return_pct") is not None),
        key=lambda row: str(row.get("observed_at") or ""),
    )
    vetoes = sum(str(row.get("action")) == "veto" for row in rows)
    approvals = sum(str(row.get("action")) in {"approve", "reduce_size"} for row in rows)
    days = len({str(row.get("observed_at") or "")[:10] for row in rows})
    minimums = {
        "option_episodes": MIN_OPTION_EPISODES, "trading_days": MIN_TRADING_DAYS,
        "veto_episodes": MIN_ACTION_EPISODES, "approval_episodes": MIN_ACTION_EPISODES,
        "holdout_episodes": MIN_HOLDOUT_EPISODES, "holdout_days": MIN_HOLDOUT_DAYS,
        "holdout_profit_factor": MIN_HOLDOUT_PROFIT_FACTOR,
    }
    base = {
        "option_episodes": len(rows), "trading_days": days, "veto_episodes": vetoes,
        "approval_episodes": approvals, "minimum_evidence": minimums,
        "training": None, "holdout": None, "recommended_for_enforcement": False,
    }
    if len(rows) < MIN_OPTION_EPISODES or days < MIN_TRADING_DAYS:
        return {**base, "status": "collecting_option_outcomes"}
    if vetoes < MIN_ACTION_EPISODES or approvals < MIN_ACTION_EPISODES:
        return {**base, "status": "collecting_action_balance"}

    holdout_count = max(MIN_HOLDOUT_EPISODES, (len(rows) + 4) // 5)
    training_rows, holdout_rows = rows[:-holdout_count], rows[-holdout_count:]
    training, holdout = _summary(training_rows), _summary(holdout_rows)
    base.update({"training": training, "holdout": holdout})
    if holdout["days"] < MIN_HOLDOUT_DAYS:
        return {**base, "status": "collecting_holdout_days"}

    train_better = float(training["incremental_avg_return_pct"] or 0) > 0
    holdout_better = float(holdout["incremental_avg_return_pct"] or 0) > 0
    holdout_profitable = float(holdout["ai_policy_avg_return_pct"] or 0) > 0
    policy_pf = holdout["ai_policy_profit_factor"]
    baseline_pf = holdout["baseline_profit_factor"]
    policy_pf_num = inf if policy_pf == "infinite" else float(policy_pf or 0)
    baseline_pf_num = inf if baseline_pf == "infinite" else float(baseline_pf or 0)
    profit_factor_pass = policy_pf_num >= MIN_HOLDOUT_PROFIT_FACTOR and policy_pf_num > baseline_pf_num
    passed = train_better and holdout_better and holdout_profitable and profit_factor_pass
    return {
        **base,
        "status": "validated_candidate" if passed else "failed_chronological_validation",
        "recommended_for_enforcement": passed,
        "checks": {
            "training_improved": train_better, "holdout_improved": holdout_better,
            "holdout_profitable": holdout_profitable,
            "holdout_profit_factor_improved": profit_factor_pass,
        },
    }
