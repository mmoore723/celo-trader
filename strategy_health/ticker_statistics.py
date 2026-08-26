"""Deterministic statistics for strategy/ticker evidence reviews."""
from __future__ import annotations

import math
import random
from statistics import median
from typing import Mapping, Sequence


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _drawdown(values: Sequence[float]) -> float:
    equity = peak = 100.0
    maximum = 0.0
    for value in values:
        equity *= 1 + value / 100.0
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * 100 if peak else 0.0)
    return maximum


def _winner_share(values: Sequence[float]) -> float:
    winners = [value for value in values if value > 0]
    total = sum(winners)
    return max(winners) / total * 100 if winners and total > 0 else 100.0


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def day_bootstrap_bounds(rows: Sequence[Mapping[str, object]], trials: int = 1000) -> dict:
    """Bootstrap whole sessions so same-day setups remain dependent."""
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row["observed_at"])[:10], []).append(float(row["return_pct"]))
    days = sorted(grouped)
    if len(days) < 5:
        return {"method": "whole_session_bootstrap", "trials": 0,
                "average_return_low_95_pct": None, "profit_factor_low_95": None}
    rng = random.Random(20260826)
    averages: list[float] = []
    factors: list[float] = []
    for _ in range(trials):
        values = [value for _day in range(len(days))
                  for value in grouped[days[rng.randrange(len(days))]]]
        averages.append(sum(values) / len(values))
        factor = profit_factor(values)
        factors.append(1e9 if factor == math.inf else float(factor or 0.0))
    average_low = _percentile(averages, 0.025)
    factor_low = _percentile(factors, 0.025)
    return {
        "method": "whole_session_bootstrap", "trials": trials,
        "average_return_low_95_pct": round(average_low, 4) if average_low is not None else None,
        "profit_factor_low_95": round(factor_low, 4) if factor_low is not None else None,
    }


def summarize(rows: Sequence[Mapping[str, object]]) -> dict:
    returns = [float(row["return_pct"]) for row in rows]
    factor = profit_factor(returns)
    costs = [float(row["entry_ask"]) * 100 for row in rows]
    spreads = [float(row["entry_spread_pct"]) for row in rows if row.get("entry_spread_pct") is not None]
    return {
        "observations": len(rows),
        "trading_days": len({str(row["observed_at"])[:10] for row in rows}),
        "profit_factor": "inf" if factor == math.inf else (round(factor, 4) if factor is not None else None),
        "median_return_pct": round(median(returns), 4) if returns else None,
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "maximum_compounded_drawdown_pct": round(_drawdown(returns), 4),
        "largest_winner_share_pct": round(_winner_share(returns), 4),
        "median_contract_cost": round(median(costs), 2) if costs else None,
        "affordable_150_1000_pct": round(sum(150 <= value <= 1000 for value in costs) / len(costs) * 100, 2) if costs else None,
        "median_entry_spread_pct": round(median(spreads), 4) if spreads else None,
        "entry_spread_coverage_pct": round(len(spreads) / len(rows) * 100, 2) if rows else None,
    }
