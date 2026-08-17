"""Reviewed strategy scope used by scanning and order routing.

The scanner deliberately has a broad job: find liquid names with movement.
This catalog has a narrow one: declare which *strategy/ticker combinations*
have actually passed the paid-quote review.  Keeping those concerns separate
lets a strategy later prove repeatable on more symbols without turning a
single-symbol result into an unsupported universal claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Iterable, Literal


SignalSource = Literal["bar_close", "live_retouch", "one_minute_state"]
StrategyStatus = Literal["paper_candidate", "retired"]
EvidenceGrade = Literal[
    "passed_declared_holdout",
    "promising_underpowered",
    "promising_inconsistent",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ReviewedStrategy:
    strategy_id: str
    display_name: str
    version: str
    tickers: frozenset[str]
    setting_key: str
    signal_source: SignalSource
    implementation: str
    exit_minutes: int | None
    paper_only: bool
    status: StrategyStatus
    evidence_grade: EvidenceGrade
    evidence_artifact: str
    evidence: str


REVIEWED_STRATEGIES: dict[str, ReviewedStrategy] = {
    "V2_ORB_PULLBACK": ReviewedStrategy(
        strategy_id="V2_ORB_PULLBACK",
        display_name="TSLA Opening-Range Pullback",
        version="2.0.0",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_orb_pullback_v2_enabled",
        signal_source="live_retouch",
        implementation="trading.orb_retouch_execution",
        exit_minutes=90,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/v2_orb_pullback-2.0.0.json",
        evidence="TSLA paid-quote first-retouch study: promising later data but negative training and inconsistent months; paper candidate only",
    ),
    "V2_SPY_TREND_CONT": ReviewedStrategy(
        strategy_id="V2_SPY_TREND_CONT",
        display_name="SPY Trend Continuation",
        version="2.0.0",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_trend_cont_v2_enabled",
        signal_source="bar_close",
        implementation="strategies.spy_trend_continuation_v2.evaluate",
        # The actual bot permits one SPY position at a time.  Under that same
        # account constraint, the 30-minute fixed hold was selected on earlier
        # paid data and passed the untouched later period (66 later trades).
        # The longer per-signal scan allowed overlapping SPY positions and is
        # diagnostic only, not the executable policy.
        exit_minutes=30,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="passed_declared_holdout",
        evidence_artifact="config/strategy_evidence/v2_spy_trend_cont-2.0.0.json",
        evidence="SPY paid-quote Trend Continuation 30-minute one-position fixed-hold study",
    ),
    "V2_SPY_AFTERNOON_FVG": ReviewedStrategy(
        strategy_id="V2_SPY_AFTERNOON_FVG",
        display_name="SPY Afternoon Fair Value Gap",
        version="2.0.0",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_afternoon_fvg_v2_enabled",
        signal_source="bar_close",
        implementation="strategies.spy_afternoon_fvg_v2.evaluate",
        exit_minutes=30,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_underpowered",
        evidence_artifact="config/strategy_evidence/v2_spy_afternoon_fvg-2.0.0.json",
        evidence="SPY paid-quote afternoon first-retest FVG study: positive May–July, but one signal short of the predeclared training minimum",
    ),
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": ReviewedStrategy(
        strategy_id="V2_TSLA_TWO_LEG_TREND_PULLBACK",
        display_name="TSLA Two-Leg Trend Pullback",
        version="2.0.0",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_tsla_two_leg_trend_pullback_v2_enabled",
        signal_source="one_minute_state",
        implementation="trading.two_leg_trend_pullback_execution",
        exit_minutes=90,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/v2_tsla_two_leg_trend_pullback-2.0.0.json",
        evidence="TSLA paid-quote VWAP/EMA two-leg study: positive train/holdout aggregate but inconsistent by month; paper candidate only",
    ),
}


def _implementation_path(implementation: str) -> Path:
    """Resolve a reviewed callable/module reference to its Python source."""
    module = implementation[:-len(".evaluate")] if implementation.endswith(".evaluate") else implementation
    return _PROJECT_ROOT / (module.replace(".", "/") + ".py")


@lru_cache(maxsize=1)
def reviewed_strategy_integrity_errors() -> dict[str, tuple[str, ...]]:
    """Return evidence/code mismatches which must fail closed for new entries.

    Evidence claims apply to an exact production implementation.  A harmless
    refactor still requires refreshing the review artifact because otherwise
    the platform cannot distinguish it from an unreviewed rule change.
    Existing positions retain their registered exit so this check never traps
    an already-open trade.
    """
    failures: dict[str, tuple[str, ...]] = {}
    for strategy_id, rule in REVIEWED_STRATEGIES.items():
        errors: list[str] = []
        evidence_path = _PROJECT_ROOT / rule.evidence_artifact
        implementation_path = _implementation_path(rule.implementation)
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures[strategy_id] = (f"evidence_unreadable:{exc.__class__.__name__}",)
            continue
        expected_fields = {
            "strategy_id": strategy_id,
            "strategy_version": rule.version,
            "status": rule.status,
            "evidence_grade": rule.evidence_grade,
            "ticker_scope": sorted(rule.tickers),
            "implementation": rule.implementation,
        }
        for field, expected in expected_fields.items():
            if evidence.get(field) != expected:
                errors.append(f"{field}_mismatch")
        try:
            actual_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
        except OSError:
            errors.append("implementation_missing")
        else:
            if actual_hash != evidence.get("implementation_sha256_at_review"):
                errors.append("implementation_hash_mismatch")
        if errors:
            failures[strategy_id] = tuple(errors)
    return failures


def public_strategy_catalog(settings: dict) -> list[dict]:
    """Return the registry's safe, UI-facing representation.

    Implementation and evidence references are intentionally included so the
    dashboard, QA report, and runtime all describe the same reviewed rule.
    The user-specific switch is resolved server-side from ``setting_key``.
    """
    integrity_errors = reviewed_strategy_integrity_errors()
    return [
        {
            "strategy_id": rule.strategy_id,
            "display_name": rule.display_name,
            "version": rule.version,
            "tickers": sorted(rule.tickers),
            "setting_key": rule.setting_key,
            "signal_source": rule.signal_source,
            "implementation": rule.implementation,
            "exit_minutes": rule.exit_minutes,
            "paper_only": rule.paper_only,
            "status": rule.status,
            "evidence_grade": rule.evidence_grade,
            "evidence_artifact": rule.evidence_artifact,
            "evidence": rule.evidence,
            "enabled": bool(settings.get(rule.setting_key, False)) and strategy_id not in integrity_errors,
            "integrity_errors": list(integrity_errors.get(strategy_id, ())),
        }
        for strategy_id, rule in REVIEWED_STRATEGIES.items()
    ]


def reviewed_strategy_ids() -> set[str]:
    """Return exact evidence-matched IDs; browser settings cannot invent one."""
    return set(REVIEWED_STRATEGIES) - set(reviewed_strategy_integrity_errors())


def is_allowed_ticker(strategy_id: object, ticker: object) -> bool:
    """Return whether a reviewed strategy may run on this ticker."""
    rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
    return bool(
        rule
        and str(strategy_id or "").strip().upper() not in reviewed_strategy_integrity_errors()
        and str(ticker or "").strip().upper() in rule.tickers
    )


def strategy_ids_for_source(source: SignalSource) -> set[str]:
    """Return the reviewed strategies owned by exactly one runtime source."""
    return {
        strategy_id for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if rule.signal_source == source
    }


def reviewed_exit_summary(strategy_id: object, *, verb: str = "exit") -> str:
    """Describe the registry-owned same-contract exit without a second map."""
    rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
    if rule is None or rule.exit_minutes is None:
        return "No reviewed exit policy is registered."
    action = "measure the executable bid" if verb == "measure" else "exit at the executable bid"
    return f"Hold the same selected contract for {rule.exit_minutes} minutes, then {action}."


def enabled_reviewed_strategy_ids(
    settings: dict, *, ticker: object | None = None, paper: bool | None = None,
) -> set[str]:
    """Return enabled reviewed IDs for this ticker and execution mode.

    The server registry—not a browser-supplied validation list—is the
    promotion authority.  A user switch can disable a reviewed rule, but it
    cannot promote an unknown one or widen its paid-evidence ticker scope.
    """
    normalized_ticker = str(ticker or "").strip().upper()
    return {
        strategy_id
        for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if strategy_id not in reviewed_strategy_integrity_errors()
        and bool(settings.get(rule.setting_key, False))
        and (not normalized_ticker or normalized_ticker in rule.tickers)
        and (paper is None or paper or not rule.paper_only)
    }


def ensure_reviewed_ticker_coverage(
    watchlist: Iterable[object], enabled_strategy_ids: Iterable[object],
) -> list[str]:
    """Keep the scanner's ranked list, appending only required pilot symbols.

    A daily scanner may rightly omit a quieter symbol.  An explicitly enabled
    reviewed setup still needs to be observed, so this only adds its validated
    ticker; it never replaces the scan's dynamic universe or changes ranking.
    """
    result = list(dict.fromkeys(
        str(ticker).strip().upper() for ticker in watchlist if str(ticker).strip()
    ))
    for strategy_id in sorted(str(value).strip().upper() for value in enabled_strategy_ids):
        rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
        if rule is None:
            continue
        for ticker in sorted(rule.tickers):
            if ticker not in result:
                result.append(ticker)
    return result
