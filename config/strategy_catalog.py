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
    "failed_profit_factor",
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
    # Research observers are evaluated by the live scanner and written to the
    # evidence ledger, but can never be returned to an order-facing path.  The
    # Settings switch controls evidence collection, not execution.
    observation_only: bool = False
    # Prospective research needs one fixed, executable same-contract mark even
    # when the eventual trading exit is still being designed.  This horizon
    # never grants order authority and is kept separate from ``exit_minutes``.
    research_exit_minutes: int | None = None
    # Structural exits still need enough session left for their first
    # completed decision bar. Zero means there is no extra entry cutoff.
    minimum_session_minutes: int = 0
    recommendation_tickers: frozenset[str] = frozenset()
    authored_exit_order_route: bool = False


REVIEWED_STRATEGIES: dict[str, ReviewedStrategy] = {
    "V2_TREND_CONT": ReviewedStrategy(
        strategy_id="V2_TREND_CONT",
        display_name="Trend Continuation",
        version="research.1",
        tickers=frozenset(),
        recommendation_tickers=frozenset({"SPY", "QQQ"}),
        setting_key="strategy_trend_cont_research_v1_enabled",
        signal_source="bar_close",
        implementation="strategies.trend_continuation_research_v1.evaluate",
        exit_minutes=None,
        minimum_session_minutes=5,
        paper_only=False,
        status="paper_candidate",
        evidence_grade="promising_underpowered",
        evidence_artifact="config/strategy_evidence/v2_trend_cont-research.1.json",
        evidence="Sequential research qualification passed for exact ticker pairs; the same execution route serves paper and live orders with explicit per-pair approval.",
        authored_exit_order_route=True,
    ),
    "V2_ORB_PULLBACK": ReviewedStrategy(
        strategy_id="V2_ORB_PULLBACK",
        display_name="TSLA Opening-Range Pullback",
        version="2.0.0",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_orb_pullback_v2_enabled",
        signal_source="live_retouch",
        implementation="trading.orb_retouch_execution",
        exit_minutes=90,
        paper_only=False,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/v2_orb_pullback-2.0.0.json",
        evidence="TSLA paid-quote first-retouch study: promising later data but negative training and inconsistent months; paper candidate only",
    ),
    "V2_SPY_TREND_CONT": ReviewedStrategy(
        strategy_id="V2_SPY_TREND_CONT",
        display_name="SPY Trend Continuation",
        version="2.1.0",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_trend_cont_v2_enabled",
        signal_source="bar_close",
        implementation="strategies.spy_trend_continuation_v2.evaluate",
        # Thirty minutes remains the tested exit while this strategy collects
        # paper evidence. The repaired order policy requires three completed
        # candles to confirm structure in the trade direction.
        exit_minutes=30,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_underpowered",
        evidence_artifact="config/strategy_evidence/v2_spy_trend_cont-2.1.0.json",
        evidence="Repaired three-candle SPY Trend policy: PF 1.75 after modeled costs across 46 exact paid-quote outcomes; paper-only pending same-broker validation",
    ),
    "V2_SPY_AFTERNOON_FVG": ReviewedStrategy(
        strategy_id="V2_SPY_AFTERNOON_FVG",
        display_name="SPY Afternoon Fair Value Gap",
        version="2.1.0",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_afternoon_fvg_v2_enabled",
        signal_source="bar_close",
        implementation="strategies.spy_afternoon_fvg_v2.evaluate",
        exit_minutes=30,
        paper_only=False,
        status="paper_candidate",
        evidence_grade="promising_underpowered",
        evidence_artifact="config/strategy_evidence/v2_spy_afternoon_fvg-2.1.0.json",
        evidence="EMA8-confirmed SPY FVG retest: after-cost PF 2.22 across 19 paid-quote outcomes; paper repair awaiting fresh forward validation",
    ),
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": ReviewedStrategy(
        strategy_id="V2_FAILED_OR_BREAK_VWAP_REVERSION",
        display_name="SPY Failed-Range Recovery",
        version="2.1.0",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_failed_range_recovery_v2_enabled",
        signal_source="bar_close",
        implementation="strategies.spy_failed_range_recovery_v2.evaluate",
        exit_minutes=30,
        paper_only=False,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/v2_spy_failed_range_recovery-2.1.0.json",
        evidence="The original 21-trade paid-option slice passed, but 383 long-history SPY episodes and four timely paper outcomes did not confirm the edge.",
    ),
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": ReviewedStrategy(
        strategy_id="V2_TSLA_TWO_LEG_TREND_PULLBACK",
        display_name="TSLA Two-Leg Trend Pullback",
        version="2.2.0",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_tsla_two_leg_trend_pullback_v2_enabled",
        signal_source="one_minute_state",
        implementation="trading.two_leg_trend_pullback_execution",
        exit_minutes=90,
        paper_only=False,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/v2_tsla_two_leg_trend_pullback-2.2.0.json",
        evidence="Fresh distinct setups may reenter after existing position and cooldown checks. Previous single-entry session returns do not validate these additional entries.",
    ),
    "CTX_ORB_NR7_OR_INSIDE": ReviewedStrategy(
        strategy_id="CTX_ORB_NR7_OR_INSIDE",
        display_name="Context-Filtered ORB (NR7 / Inside Day)",
        version="0.1.0",
        tickers=frozenset({"SPY", "QQQ", "TSLA", "AMZN"}),
        setting_key="observe_ctx_orb_nr7_inside_enabled",
        signal_source="bar_close",
        implementation="strategies.context_strategy_observers",
        exit_minutes=None,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_inconsistent",
        evidence_artifact="config/strategy_evidence/ctx_orb_nr7_inside-0.1.0.json",
        evidence="Paid-quote replay found PF 1.70 for the TSLA $150-$250 slice, but the broader result and chronological stability did not pass.",
        observation_only=True,
    ),
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG": ReviewedStrategy(
        strategy_id="CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG",
        display_name="Context-Filtered ORB (ATR10)",
        version="0.1.0",
        tickers=frozenset({"SPY", "QQQ", "TSLA", "AMZN"}),
        setting_key="observe_ctx_orb_atr10_enabled",
        signal_source="bar_close",
        implementation="strategies.context_strategy_observers",
        exit_minutes=None,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="failed_profit_factor",
        evidence_artifact="config/strategy_evidence/ctx_orb_atr10-0.1.0.json",
        evidence="The largest TSLA $150-$250 cohort produced PF 0.95, below the 1.50 target.",
        observation_only=True,
    ),
    "CTX_VWAP_PULLBACK_KER10_LONG": ReviewedStrategy(
        strategy_id="CTX_VWAP_PULLBACK_KER10_LONG",
        display_name="VWAP Pullback (1-Hour KER)",
        version="0.1.0",
        tickers=frozenset({"SPY", "QQQ", "TSLA", "AMZN"}),
        setting_key="observe_ctx_vwap_ker_enabled",
        signal_source="bar_close",
        implementation="strategies.context_strategy_observers",
        exit_minutes=None,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="failed_profit_factor",
        evidence_artifact="config/strategy_evidence/ctx_vwap_ker-0.1.0.json",
        evidence="The largest corrected paid-quote cohort produced PF 0.51 on TSLA, below the 1.50 target.",
        observation_only=True,
    ),
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG": ReviewedStrategy(
        strategy_id="CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
        display_name="VWAP Pullback (10:30 Displacement)",
        version="0.2.0",
        tickers=frozenset({"TSLA", "AMZN"}),
        setting_key="observe_ctx_vwap_displacement_enabled",
        signal_source="bar_close",
        implementation="strategies.context_strategy_observers",
        # The paid strategy itself exits at the frozen prior-day high, the
        # first completed five-minute close through VWAP, or the 15:55 cap.
        # A separate 90-minute quote remains useful for comparable research.
        exit_minutes=None,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="promising_underpowered",
        evidence_artifact="config/strategy_evidence/ctx_vwap_displacement-0.2.0.json",
        evidence="The evidence-matched structural paper exit produced PF 7.21 across six real paid-contract outcomes after current modeled costs; promising but far too small for launch proof.",
        observation_only=False,
        research_exit_minutes=90,
        minimum_session_minutes=5,
    ),
    "CTX_1H_SQUEEZE_MACD_LONG": ReviewedStrategy(
        strategy_id="CTX_1H_SQUEEZE_MACD_LONG",
        display_name="1-Hour Bollinger / Keltner Squeeze",
        version="0.1.0",
        tickers=frozenset({"QQQ"}),
        setting_key="observe_ctx_squeeze_macd_enabled",
        signal_source="bar_close",
        implementation="strategies.context_strategy_observers",
        exit_minutes=None,
        paper_only=True,
        status="paper_candidate",
        evidence_grade="failed_profit_factor",
        evidence_artifact="config/strategy_evidence/ctx_squeeze_macd-0.1.0.json",
        evidence="QQQ produced no executable option fills for the exact squeeze rule in the purchased archive.",
        observation_only=True,
    ),
}


from config.research_order_specs import SPECS as _RESEARCH_ORDERS, setting_key as _research_setting

for _sid, _spec in _RESEARCH_ORDERS.items():
    REVIEWED_STRATEGIES[_sid] = ReviewedStrategy(
        strategy_id=_sid, display_name=_spec.name, version=_spec.version,
        tickers=frozenset(), recommendation_tickers=frozenset(),
        setting_key=_research_setting(_sid), signal_source='bar_close',
        implementation='strategies.research_orders', exit_minutes=None,
        research_exit_minutes=_spec.reference_minutes, minimum_session_minutes=_spec.timeframe,
        paper_only=False, status='paper_candidate', evidence_grade='promising_underpowered',
        evidence_artifact=f'config/strategy_evidence/{_sid.lower()}-orders.json',
        evidence='Exact research rules connected to broker execution. Admin approval is not a profitability claim.',
        authored_exit_order_route=True,
    )


def _backtest_display(rule: ReviewedStrategy) -> dict:
    """Return compact, pre-reviewed metrics for the Settings control.

    The UI never infers a PF from arbitrary report shapes.  The evidence
    artifact records the exact cohort selected for display, including sample
    size and scope, so a tiny winning slice cannot masquerade as a universal
    strategy result.
    """
    try:
        evidence = json.loads((_PROJECT_ROOT / rule.evidence_artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    display = evidence.get("display_metrics")
    result = dict(display) if isinstance(display, dict) else {}
    for field in ("historical_test_through", "forward_evidence_start"):
        if isinstance(evidence.get(field), str):
            result[field] = evidence[field]
    return result


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
        display_metrics = evidence.get("display_metrics")
        if (
            rule.evidence_grade == "passed_declared_holdout"
            and (
                not isinstance(display_metrics, dict)
                or display_metrics.get("meets_target") is not True
            )
        ):
            errors.append("declared_pass_does_not_meet_target")
        try:
            actual_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
        except OSError:
            errors.append("implementation_missing")
        else:
            if actual_hash != evidence.get("implementation_sha256_at_review"):
                errors.append("implementation_hash_mismatch")
        policy_sources = evidence.get("runtime_policy_sources", [])
        # Historical evidence stays immutable. Only an explicitly selected,
        # separately validated runtime review can supersede its source pins.
        from config.runtime_exit_review import review
        try:
            runtime_review = review(rule, evidence, root=_PROJECT_ROOT)
            if runtime_review is not None:
                policy_sources = runtime_review['runtime_policy_sources']
        except (OSError, ValueError, KeyError, TypeError):
            errors.append('runtime_review_invalid')
        if not isinstance(policy_sources, list):
            errors.append("runtime_policy_sources_invalid")
        else:
            for source in policy_sources:
                if not isinstance(source, dict) or not source.get("path") or not source.get("sha256"):
                    errors.append("runtime_policy_source_invalid")
                    continue
                try:
                    policy_path = (_PROJECT_ROOT / str(source["path"])).resolve()
                    policy_path.relative_to(_PROJECT_ROOT.resolve())
                    policy_hash = hashlib.sha256(policy_path.read_bytes()).hexdigest()
                except (OSError, ValueError):
                    errors.append("runtime_policy_source_missing")
                else:
                    if policy_hash != source["sha256"]:
                        errors.append("runtime_policy_source_hash_mismatch")
        if errors:
            failures[strategy_id] = tuple(errors)
    return failures


def public_strategy_catalog(settings: dict) -> list[dict]:
    """Return the registry's safe, UI-facing representation.

    Implementation and evidence references are intentionally included so the
    dashboard, QA report, and runtime all describe the same reviewed rule.
    The user-specific switch is resolved server-side from ``setting_key``.
    """
    from config.strategy_live_promotion import review_live_promotion
    from config.strategy_retirement import is_retired

    integrity_errors = reviewed_strategy_integrity_errors()
    account_mode = "paper" if bool(settings.get("paper_trading", True)) else "live"
    rows = []
    for strategy_id, rule in REVIEWED_STRATEGIES.items():
        promotion = review_live_promotion(rule)
        from config.strategy_ticker_recommendations import is_user_authorized_ticker
        from config.admin_strategy_overrides import tickers as override_tickers
        pair_grants = {grant.get('ticker') for grant in (settings.get('strategy_pair_approvals') or {}).values()
                       if grant.get('strategy_id') == strategy_id and grant.get('ticker')}
        approved_tickers = sorted(ticker for ticker in rule.recommendation_tickers | set(override_tickers(settings, strategy_id)) | pair_grants
                                  if is_user_authorized_ticker(strategy_id, ticker, settings))
        from strategy_health.closed_trade_guard import scope
        automatic_pauses = settings.get('strategy_closed_trade_pauses') or {}
        rows.append({
            "strategy_id": rule.strategy_id,
            "removed": is_retired(settings, strategy_id, rule.version),
            "research_source_strategy_id": _RESEARCH_ORDERS[strategy_id].source if strategy_id in _RESEARCH_ORDERS else strategy_id,
            "display_name": rule.display_name,
            "version": rule.version,
            "tickers": sorted(rule.tickers | set(approved_tickers)),
            "trading_tickers": sorted(ticker for ticker in (rule.tickers | set(approved_tickers))
                                      if strategy_id in enabled_reviewed_strategy_ids(settings, ticker=ticker)),
            "automatic_pauses": [{"ticker": ticker, **automatic_pauses[scope(settings, strategy_id, ticker, rule.version)]}
                                 for ticker in sorted(rule.tickers | rule.recommendation_tickers | set(override_tickers(settings, strategy_id)) | pair_grants)
                                 if scope(settings, strategy_id, ticker, rule.version) in automatic_pauses],
            "setting_key": rule.setting_key,
            "signal_source": rule.signal_source,
            "implementation": rule.implementation,
            "exit_minutes": rule.exit_minutes,
            "research_exit_minutes": reviewed_research_exit_minutes(rule.strategy_id),
            "minimum_session_minutes": rule.minimum_session_minutes,
            "paper_only": rule.paper_only,
            "status": rule.status,
            "evidence_grade": rule.evidence_grade,
            "evidence_artifact": rule.evidence_artifact,
            "evidence": rule.evidence,
            "backtest": _backtest_display(rule),
            "research_scope": "all_collected_tickers",
            "control_kind": "observation" if rule.observation_only else "execution",
            "observation_only": rule.observation_only,
            "enabled": bool(settings.get(rule.setting_key, False)) and rule.strategy_id not in integrity_errors,
            # Keep the user's switch separate from integrity eligibility. Once
            # a catalog strategy has passed review, the same exact version may
            # execute in paper or live mode when this user turns it on.
            "account_mode": account_mode,
            "live_eligible": not rule.paper_only and not rule.observation_only,
            # Qualification is independent of the connected broker mode. A
            # live account can shadow real market conditions with zero order
            # authority while an exact strategy version is still qualifying.
            "validation_state": (
                "qualified_for_live"
                if not rule.paper_only and not rule.observation_only
                else "shadow_observation"
            ),
            "observation_requires_paper_mode": False,
            "eligible_in_current_mode": (
                not rule.observation_only
                and (account_mode == "paper" or not rule.paper_only)
            ),
            "execution_enabled": (
                bool(settings.get(rule.setting_key, False))
                and rule.strategy_id not in integrity_errors
                and not rule.observation_only
                and (account_mode == "paper" or not rule.paper_only)
            ),
            "observation_enabled": (
                bool(settings.get(rule.setting_key, False))
                and rule.strategy_id not in integrity_errors
                and rule.observation_only
            ),
            "integrity_errors": list(integrity_errors.get(rule.strategy_id, ())),
            "live_promotion": promotion.public(),
        })
    return rows


def reviewed_strategy_ids() -> set[str]:
    """Return exact evidence-matched IDs; browser settings cannot invent one."""
    return set(REVIEWED_STRATEGIES) - set(reviewed_strategy_integrity_errors())


def reviewed_execution_strategy_ids() -> set[str]:
    """Return integrity-matched strategies which are allowed to reach orders."""
    return {
        strategy_id for strategy_id in reviewed_strategy_ids()
        if not REVIEWED_STRATEGIES[strategy_id].observation_only
    }


def reviewed_research_exit_minutes(strategy_id: object) -> int:
    """Return the fixed forward mark used only for cross-ticker research."""
    rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
    if rule is None:
        return 90
    return int(rule.research_exit_minutes or rule.exit_minutes or 90)


def enabled_observation_strategy_ids(
    settings: dict, *, ticker: object | None = None,
) -> set[str]:
    """Return user-enabled, fail-closed research observers for one ticker."""
    from config.strategy_retirement import is_retired
    return {
        strategy_id
        for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if rule.observation_only
        and not is_retired(settings, strategy_id, rule.version)
        and strategy_id not in reviewed_strategy_integrity_errors()
        and bool(settings.get(rule.setting_key, False))
    }


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
    if rule is None:
        return "No reviewed exit policy is registered."
    if rule.strategy_id in _RESEARCH_ORDERS:
        from strategy_health.exit_measurement import exit_measurement
        return exit_measurement(rule.strategy_id, rule.research_exit_minutes)['authored_exit']
    if rule.strategy_id == "V2_TREND_CONT":
        return "Exit at the frozen underlying stop or 2R target after a completed 5-minute candle, with the tested 75-bar time cap and session close backstop."
    if verb == "measure":
        minutes = reviewed_research_exit_minutes(rule.strategy_id)
        return f"Hold the same selected contract for {minutes} minutes, then measure the executable bid."
    if rule.strategy_id == "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG":
        return (
            "Exit when the underlying reaches the frozen prior high, the first "
            "completed 5-minute candle closes below session VWAP, or at 3:55 PM ET."
        )
    if rule.exit_minutes is None:
        return "No order exit is registered; this strategy records research only."
    return f"Hold the same selected contract for {rule.exit_minutes} minutes, then exit at the executable bid."


def enabled_reviewed_strategy_ids(
    settings: dict, *, ticker: object | None = None, paper: bool | None = None,
) -> set[str]:
    """Return enabled reviewed IDs for this ticker and execution mode.

    The server registry—not a browser-supplied validation list—is the
    promotion authority.  A user switch can disable a reviewed rule, but it
    cannot promote an unknown one or widen its paid-evidence ticker scope.
    """
    normalized_ticker = str(ticker or "").strip().upper()
    from config.strategy_ticker_recommendations import (
        has_user_live_enabled, has_user_paper_enabled, is_live_enabled_pair,
        is_paper_enabled_pair, is_user_authorized_ticker,
    )
    is_paper = bool(settings.get("paper_trading", True)) if paper is None else bool(paper)
    from config.strategy_retirement import is_retired

    def _mode_eligible(strategy_id: str, rule: ReviewedStrategy) -> bool:
        if rule.observation_only:
            if not is_paper:
                return False
            return (
                is_paper_enabled_pair(strategy_id, normalized_ticker, settings)
                if normalized_ticker else has_user_paper_enabled(strategy_id, settings)
            )
        if is_paper or not rule.paper_only:
            return True
        # Keep rules without general live-order authority out of ordinary live
        # execution. This does not require the account to switch to paper. The
        # sole exception is an exact dynamic ticker which passed live review
        # and this user explicitly enabled. Before ticker selection, retain the
        # strategy only if this user has at least one such live approval.
        if normalized_ticker:
            return is_live_enabled_pair(strategy_id, normalized_ticker, settings)
        return has_user_live_enabled(strategy_id, settings)
    return {
        strategy_id
        for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if strategy_id not in reviewed_strategy_integrity_errors()
        and not is_retired(settings, strategy_id, rule.version)
        and bool(settings.get(rule.setting_key, False))
        and (not normalized_ticker or is_user_authorized_ticker(strategy_id, normalized_ticker, settings))
        and _mode_eligible(strategy_id, rule)
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
