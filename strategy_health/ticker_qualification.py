"""Causal qualification of reviewed strategy/ticker observations.

This module is deliberately separated from order routing.  It consumes only
completed, same-contract option observations and returns evidence.  It cannot
enable a strategy, change settings, or submit an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import sqlite3
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

from config.strategy_catalog import REVIEWED_STRATEGIES


@dataclass(frozen=True)
class QualificationPolicy:
    minimum_total: int = 30
    minimum_days: int = 10
    minimum_holdout: int = 10
    minimum_holdout_days: int = 3
    training_fraction: float = 0.70
    minimum_training_profit_factor: float = 1.20
    minimum_holdout_profit_factor: float = 1.10
    maximum_drawdown_pct: float = 20.0
    maximum_winner_concentration_pct: float = 35.0


DEFAULT_POLICY = QualificationPolicy()


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _maximum_drawdown(values: Sequence[float]) -> float:
    equity = peak = 100.0
    maximum = 0.0
    for value in values:
        equity *= 1 + value / 100.0
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * 100 if peak else 0.0)
    return maximum


def _winner_concentration(values: Sequence[float]) -> float:
    winners = [value for value in values if value > 0]
    total = sum(winners)
    return max(winners) / total * 100 if winners and total > 0 else 100.0


def _metrics(rows: Sequence[Mapping[str, object]]) -> dict:
    returns = [float(row["return_pct"]) for row in rows]
    factor = _profit_factor(returns)
    return {
        "observations": len(rows),
        "trading_days": len({str(row["observed_at"])[:10] for row in rows}),
        "profit_factor": "inf" if factor == math.inf else (round(factor, 4) if factor is not None else None),
        "median_return_pct": round(median(returns), 4) if returns else None,
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "maximum_compounded_drawdown_pct": round(_maximum_drawdown(returns), 4),
        "largest_winner_share_pct": round(_winner_concentration(returns), 4),
    }


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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
        entry_ask = _number(raw.get("entry_ask"))
        exit_bid = _number(raw.get("exit_bid"))
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
        return_pct = (exit_bid - entry_ask) / entry_ask * 100
        row = {
            "candidate_id": str(raw.get("candidate_id") or ""),
            "strategy_id": sid,
            "strategy_version": rule.version,
            "ticker": ticker,
            "observed_at": observed.isoformat(),
            "contract_symbol": str(raw.get("contract_symbol")),
            "entry_ask": round(entry_ask, 6),
            "exit_bid": round(exit_bid, 6),
            "return_pct": round(return_pct, 6),
        }
        key = (sid, ticker, observed.isoformat()[:16], row["contract_symbol"])
        accepted.setdefault(key, row)
    return sorted(accepted.values(), key=lambda row: row["observed_at"]), exclusions


def qualify_pair(
    strategy_id: str, ticker: str, rows: Iterable[Mapping[str, object]],
    *, policy: QualificationPolicy = DEFAULT_POLICY,
) -> dict:
    sid, symbol = strategy_id.strip().upper(), ticker.strip().upper()
    normalized, exclusions = normalize_completed_observations(rows)
    samples = [row for row in normalized if row["strategy_id"] == sid and row["ticker"] == symbol]
    days = sorted({row["observed_at"][:10] for row in samples})
    minimum_reasons = []
    if len(samples) < policy.minimum_total:
        minimum_reasons.append(f"need_{policy.minimum_total}_completed_observations")
    if len(days) < policy.minimum_days:
        minimum_reasons.append(f"need_{policy.minimum_days}_trading_days")
    if minimum_reasons:
        return {
            "decision": "insufficient_evidence", "strategy_id": sid, "ticker": symbol,
            "strategy_version": getattr(REVIEWED_STRATEGIES.get(sid), "version", None),
            "reasons": minimum_reasons, "metrics": _metrics(samples), "exclusions": exclusions,
        }

    # Split on a whole trading-day boundary so no same-session observation can
    # leak across training and holdout.
    split_day_index = max(1, min(len(days) - policy.minimum_holdout_days, math.floor(len(days) * policy.training_fraction)))
    holdout_start = days[split_day_index]
    training = [row for row in samples if row["observed_at"][:10] < holdout_start]
    holdout = [row for row in samples if row["observed_at"][:10] >= holdout_start]
    if len(holdout) < policy.minimum_holdout or len({row["observed_at"][:10] for row in holdout}) < policy.minimum_holdout_days:
        return {
            "decision": "insufficient_evidence", "strategy_id": sid, "ticker": symbol,
            "strategy_version": REVIEWED_STRATEGIES[sid].version,
            "reasons": [f"need_{policy.minimum_holdout}_holdout_observations", f"need_{policy.minimum_holdout_days}_holdout_days"],
            "holdout_start": holdout_start, "metrics": _metrics(samples), "exclusions": exclusions,
        }
    train_metrics, holdout_metrics = _metrics(training), _metrics(holdout)

    def factor_value(value: object) -> float:
        return math.inf if value == "inf" else float(value or 0)

    failures = []
    if factor_value(train_metrics["profit_factor"]) < policy.minimum_training_profit_factor:
        failures.append("training_profit_factor")
    if factor_value(holdout_metrics["profit_factor"]) < policy.minimum_holdout_profit_factor:
        failures.append("holdout_profit_factor")
    if float(train_metrics["median_return_pct"] or 0) <= 0:
        failures.append("training_median")
    if float(holdout_metrics["median_return_pct"] or 0) <= 0:
        failures.append("holdout_median")
    if float(holdout_metrics["maximum_compounded_drawdown_pct"] or 0) > policy.maximum_drawdown_pct:
        failures.append("holdout_drawdown")
    if float(holdout_metrics["largest_winner_share_pct"] or 100) > policy.maximum_winner_concentration_pct:
        failures.append("winner_concentration")
    return {
        "decision": "qualified" if not failures else "rejected",
        "strategy_id": sid, "ticker": symbol,
        "strategy_version": REVIEWED_STRATEGIES[sid].version,
        "holdout_start": holdout_start, "reasons": failures,
        "training": train_metrics, "holdout": holdout_metrics,
        "all_observations": _metrics(samples), "exclusions": exclusions,
    }


def load_completed_observations(db_paths: Iterable[Path]) -> list[dict]:
    """Read completed candidate quote pairs from one or more account DBs."""
    rows: list[dict] = []
    for path in db_paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            available = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"shadow_candidates", "candidate_option_quote_observations"}.issubset(available):
                continue
            for row in conn.execute(
                """SELECT s.candidate_id, s.observed_at, s.ticker, s.strategy_id,
                          s.metadata_json, e.contract_symbol, e.ask AS entry_ask,
                          x.bid AS exit_bid, x.observation_kind AS exit_kind
                   FROM shadow_candidates s
                   JOIN candidate_option_quote_observations e
                     ON e.candidate_id=s.candidate_id AND e.observation_kind='entry'
                   JOIN candidate_option_quote_observations x
                     ON x.candidate_id=s.candidate_id
                   WHERE x.observation_kind IN ('mark_30m','mark_60m','mark_90m')"""
            ):
                rule = REVIEWED_STRATEGIES.get(str(row["strategy_id"]).upper())
                expected_kind = f"mark_{rule.exit_minutes}m" if rule and rule.exit_minutes else None
                if row["exit_kind"] != expected_kind:
                    continue
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    metadata = {}
                rows.append({
                    **dict(row),
                    "strategy_version": metadata.get("strategy_version") if isinstance(metadata, dict) else None,
                })
        finally:
            conn.close()
    return rows

