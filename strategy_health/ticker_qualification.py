"""Causal qualification of reviewed strategy/ticker observations.

This module is deliberately separated from order routing.  It consumes only
completed, same-contract option observations and returns evidence.  It cannot
enable a strategy, change settings, or submit an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable, Mapping

from config.market_constants import COMMISSION_PER_CONTRACT
from config.strategy_catalog import REVIEWED_STRATEGIES
from strategy_health.ticker_observations import load_completed_observations
from strategy_health.ticker_statistics import day_bootstrap_bounds, number, summarize


@dataclass(frozen=True)
class QualificationPolicy:
    minimum_observed_sessions: int = 20
    minimum_inference_days: int = 5
    minimum_holdout_days: int = 3
    training_fraction: float = 0.70
    target_profit_factor: float = 1.50
    minimum_confident_profit_factor: float = 1.00
    maximum_drawdown_pct: float = 20.0
    maximum_winner_concentration_pct: float = 35.0


DEFAULT_POLICY = QualificationPolicy()


def normalize_completed_observations(rows: Iterable[Mapping[str, object]]) -> tuple[list[dict], dict]:
    """Validate and deduplicate executable observations.

    Duplicate scanner observations from multiple user accounts are collapsed
    by strategy, ticker, minute, and contract. They must never masquerade as
    independent market samples.
    """
    accepted: dict[tuple[str, str, str, str], dict] = {}
    exclusions: dict[str, int] = {}
    for raw in rows:
        sid = str(raw.get("strategy_id") or "").strip().upper()
        ticker = str(raw.get("ticker") or "").strip().upper()
        rule = REVIEWED_STRATEGIES.get(sid)
        reason = None
        if rule is None:
            reason = "unknown_strategy"
        elif str(raw.get("strategy_version") or "") != rule.version:
            reason = "version_mismatch_or_missing"
        elif str(raw.get("contract_symbol") or "") == "":
            reason = "missing_contract"
        entry_ask = number(raw.get("entry_ask"))
        entry_bid = number(raw.get("entry_bid"))
        exit_bid = number(raw.get("exit_bid"))
        if reason is None and (entry_ask is None or entry_ask <= 0):
            reason = "missing_entry_ask"
        if reason is None and (exit_bid is None or exit_bid < 0):
            reason = "missing_exit_bid"
        try:
            observed = datetime.fromisoformat(str(raw.get("observed_at")))
        except (TypeError, ValueError):
            observed = None
            reason = reason or "invalid_observed_at"
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            continue
        gross_return_pct = (exit_bid - entry_ask) / entry_ask * 100
        round_trip_fee = 2 * COMMISSION_PER_CONTRACT
        return_pct = ((exit_bid - entry_ask) * 100 - round_trip_fee) / (entry_ask * 100) * 100
        spread = None
        if entry_bid is not None and entry_bid >= 0 and entry_ask + entry_bid > 0:
            spread = (entry_ask - entry_bid) / ((entry_ask + entry_bid) / 2) * 100
        row = {
            "candidate_id": str(raw.get("candidate_id") or ""),
            "strategy_id": sid,
            "strategy_version": rule.version,
            "ticker": ticker,
            "observed_at": observed.isoformat(),
            "contract_symbol": str(raw.get("contract_symbol")),
            "entry_bid": entry_bid,
            "entry_ask": round(entry_ask, 6),
            "exit_bid": round(exit_bid, 6),
            "entry_spread_pct": round(spread, 6) if spread is not None else None,
            "gross_return_pct": round(gross_return_pct, 6),
            "round_trip_fee": round(round_trip_fee, 4),
            "return_pct": round(return_pct, 6),
        }
        key = (sid, ticker, observed.isoformat()[:16], row["contract_symbol"])
        accepted.setdefault(key, row)
    return sorted(accepted.values(), key=lambda row: row["observed_at"]), exclusions


def qualify_pair(
    strategy_id: str, ticker: str, rows: Iterable[Mapping[str, object]],
    *, policy: QualificationPolicy = DEFAULT_POLICY,
    exposure: Mapping[str, object] | None = None,
    declared_holdout_start: str | None = None,
) -> dict:
    sid, symbol = strategy_id.strip().upper(), ticker.strip().upper()
    normalized, exclusions = normalize_completed_observations(rows)
    samples = [row for row in normalized if row["strategy_id"] == sid and row["ticker"] == symbol]
    days = sorted({row["observed_at"][:10] for row in samples})
    observed_sessions = int((exposure or {}).get("observed_sessions") or len(days))
    behavior = {
        "observed_sessions": observed_sessions, "completed_setup_days": len(days),
        "setups_per_20_observed_sessions": round(len(samples) / observed_sessions * 20, 2) if observed_sessions else 0.0,
        "exposure_source": (exposure or {}).get("source", "completed_setups_only"),
        "first_observed": (exposure or {}).get("first_observed"),
        "last_observed": (exposure or {}).get("last_observed"),
    }
    base = {
        "strategy_id": sid, "ticker": symbol,
        "scope": "exact_strategy_version_and_ticker",
        "strategy_version": getattr(REVIEWED_STRATEGIES.get(sid), "version", None),
        "ticker_behavior": behavior, "all_observations": summarize(samples), "exclusions": exclusions,
    }
    if observed_sessions < policy.minimum_observed_sessions:
        return {**base, "decision": "insufficient_evidence",
                "evidence_state": "insufficient_market_exposure",
                "reasons": ["need_more_observed_market_sessions"]}
    if len(days) < policy.minimum_inference_days + policy.minimum_holdout_days:
        factor = base["all_observations"]["profit_factor"]
        point_positive = (math.inf if factor == "inf" else float(factor or 0)) > 1
        decision = "promising_monitor" if point_positive else "insufficient_evidence"
        return {**base, "decision": decision, "evidence_state": decision,
                "reasons": ["natural_cadence_has_not_produced_enough_independent_days"]}

    frozen_boundary = bool(
        declared_holdout_start
        and days[0] < declared_holdout_start <= days[-1]
    )
    if frozen_boundary:
        holdout_start = declared_holdout_start
    else:
        split = max(policy.minimum_inference_days,
                    min(len(days) - policy.minimum_holdout_days,
                        math.floor(len(days) * policy.training_fraction)))
        holdout_start = days[split]
    training = [row for row in samples if row["observed_at"][:10] < holdout_start]
    holdout = [row for row in samples if row["observed_at"][:10] >= holdout_start]
    train_metrics, holdout_metrics = summarize(training), summarize(holdout)
    uncertainty = day_bootstrap_bounds(holdout)

    def factor_value(value: object) -> float:
        return math.inf if value == "inf" else float(value or 0)

    failures = []
    if factor_value(train_metrics["profit_factor"]) < policy.target_profit_factor:
        failures.append("training_profit_factor_below_target")
    if factor_value(holdout_metrics["profit_factor"]) < policy.target_profit_factor:
        failures.append("holdout_profit_factor_below_target")
    if float(uncertainty["profit_factor_low_95"] or 0) < policy.minimum_confident_profit_factor:
        failures.append("holdout_profit_not_yet_confident")
    if float(uncertainty["average_return_low_95_pct"] or 0) <= 0:
        failures.append("holdout_expectancy_not_yet_confident")
    if float(holdout_metrics["maximum_compounded_drawdown_pct"] or 0) > policy.maximum_drawdown_pct:
        failures.append("holdout_drawdown")
    if float(holdout_metrics["largest_winner_share_pct"] or 100) > policy.maximum_winner_concentration_pct:
        failures.append("winner_concentration")
    point_positive = (
        factor_value(train_metrics["profit_factor"]) > 1
        and factor_value(holdout_metrics["profit_factor"]) > 1
        and float(train_metrics["average_return_pct"] or 0) > 0
        and float(holdout_metrics["average_return_pct"] or 0) > 0
    )
    decision = "qualified" if not failures else ("promising_monitor" if point_positive else "rejected")
    return {**base,
        "decision": decision, "evidence_state": decision,
        "holdout_start": holdout_start, "reasons": failures,
        "holdout_boundary": "frozen_declared" if frozen_boundary else "newly_declared",
        "training": train_metrics, "holdout": holdout_metrics,
        "holdout_uncertainty": uncertainty,
    }
