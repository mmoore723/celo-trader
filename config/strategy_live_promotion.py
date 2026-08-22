"""Explain whether an exact reviewed strategy version is ready for live use.

Account mode and validation mode are deliberately separate.  A live-connected
account may shadow-observe a candidate indefinitely.  This module only reports
whether the platform has enough evidence to *offer* per-user live activation;
it never changes a setting or authorizes an order by itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BROKER_AUDIT = _PROJECT_ROOT / "reports/broker_execution_audit_ec2_snapshot.json"


@dataclass(frozen=True)
class LivePromotionReview:
    ready: bool
    stage: str
    passed: tuple[str, ...]
    blockers: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "stage": self.stage,
            "passed": list(self.passed),
            "blockers": list(self.blockers),
        }


def _count(evidence: dict[str, Any], bucket: str) -> int:
    row = evidence.get(bucket) or {}
    return int(row.get("measured_signals", row.get("trades", 0)) or 0)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def review_live_promotion(rule: Any, ticker: str | None = None) -> LivePromotionReview:
    """Evaluate transparent, conservative prerequisites for live eligibility.

    Passing this function does not promote anything; it makes the remaining
    work machine-readable and prevents a vague permanent "not live" state.
    When ``ticker`` is supplied, the prospective evidence is scoped to that
    exact strategy/version/ticker pair.  This lets a live-connected account
    observe and later pilot a newly qualified pair without changing the
    account back to paper or globally promoting every ticker in the catalog.
    """
    evidence = _read_json(_PROJECT_ROOT / rule.evidence_artifact)
    passed: list[str] = []
    blockers: list[str] = []

    if rule.evidence_grade == "passed_declared_holdout":
        passed.append("Chronological historical holdout passed")
    else:
        blockers.append(
            "Historical review is not stable enough: "
            + rule.evidence_grade.replace("_", " ")
        )

    holdout_count = _count(evidence, "holdout")
    if holdout_count >= 30:
        passed.append(f"Historical holdout sample is adequate ({holdout_count})")
    else:
        blockers.append(f"Historical holdout needs at least 30 executable outcomes ({holdout_count}/30)")

    market_data = evidence.get("market_data") or {}
    execution_model = str(market_data.get("execution_model", "")).lower()
    if "actual option ask" in execution_model and "actual bid" in execution_model:
        passed.append("Historical entries and exits use real option bid/ask quotes")
    else:
        blockers.append("Historical option entry/exit quote evidence is incomplete")

    # Prospective evidence must be written for this exact strategy version by
    # the account-scoped recorder.  Absence is an honest blocker, not a reason
    # to force a live user to change the entire account back to paper mode.
    prospective_suffix = f"-{str(ticker).strip().upper()}" if ticker else ""
    prospective_path = _PROJECT_ROOT / "reports/live_promotion" / f"{rule.strategy_id}-{rule.version}{prospective_suffix}.json"
    prospective = _read_json(prospective_path)
    closed = int(prospective.get("closed_outcomes", 0) or 0)
    expectancy = prospective.get("expectancy_dollars")
    profit_factor = prospective.get("profit_factor")
    lifecycle_errors = int(prospective.get("unresolved_lifecycle_errors", 0) or 0)
    if closed >= 20 and expectancy is not None and float(expectancy) > 0 and profit_factor is not None and float(profit_factor) >= 1.2:
        passed.append(f"Prospective shadow sample passed ({closed} closed outcomes)")
    else:
        blockers.append(
            "Prospective shadow evidence needs 20 closed outcomes, positive expectancy, and profit factor ≥ 1.20"
            f" ({closed}/20 recorded)"
        )
    if lifecycle_errors:
        blockers.append(f"Prospective lifecycle audit has {lifecycle_errors} unresolved error(s)")

    broker = _read_json(_BROKER_AUDIT).get("by_intent", {})
    entry = broker.get("buy_to_open", {})
    exit_ = broker.get("sell_to_close", {})
    entry_rate = float(entry.get("fill_rate_pct", 0) or 0)
    exit_rate = float(exit_.get("fill_rate_pct", 0) or 0)
    exit_issues = int(exit_.get("attempts_with_issues", 0) or 0)
    if entry_rate >= 80 and exit_rate >= 80 and exit_issues == 0:
        passed.append("Broker entry/exit lifecycle meets the live execution gate")
    else:
        blockers.append(
            "Broker execution gate failed: "
            f"entry fills {entry_rate:.1f}%, exit fills {exit_rate:.1f}%, unresolved exit attempts {exit_issues}"
        )

    if not blockers and ticker:
        stage = "pair_live_eligible"
        ready = True
    elif not blockers and not rule.paper_only:
        stage = "live_eligible"
        ready = True
    elif not blockers:
        stage = "review_ready"
        ready = False
        blockers.append("Final reviewed catalog promotion has not been released")
    else:
        stage = "shadow_observation"
        ready = False
    return LivePromotionReview(ready=ready, stage=stage, passed=tuple(passed), blockers=tuple(blockers))
