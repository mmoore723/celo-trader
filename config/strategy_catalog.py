"""Reviewed strategy scope used by scanning and order routing.

The scanner deliberately has a broad job: find liquid names with movement.
This catalog has a narrow one: declare which *strategy/ticker combinations*
have actually passed the paid-quote review.  Keeping those concerns separate
lets a strategy later prove repeatable on more symbols without turning a
single-symbol result into an unsupported universal claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


SignalSource = Literal["bar_close", "live_retouch", "one_minute_state"]
StrategyStatus = Literal["paper_candidate", "retired"]


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
        evidence_artifact="config/strategy_evidence/v2_tsla_two_leg_trend_pullback-2.0.0.json",
        evidence="TSLA paid-quote VWAP/EMA two-leg study: positive train/holdout aggregate but inconsistent by month; paper candidate only",
    ),
}


def public_strategy_catalog(settings: dict) -> list[dict]:
    """Return the registry's safe, UI-facing representation.

    Implementation and evidence references are intentionally included so the
    dashboard, QA report, and runtime all describe the same reviewed rule.
    The user-specific switch is resolved server-side from ``setting_key``.
    """
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
            "evidence_artifact": rule.evidence_artifact,
            "evidence": rule.evidence,
            "enabled": bool(settings.get(rule.setting_key, False)),
        }
        for rule in REVIEWED_STRATEGIES.values()
    ]


def reviewed_strategy_ids() -> set[str]:
    """Return server-reviewed IDs; browser settings cannot invent one."""
    return set(REVIEWED_STRATEGIES)


def is_allowed_ticker(strategy_id: object, ticker: object) -> bool:
    """Return whether a reviewed strategy may run on this ticker."""
    rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
    return bool(rule and str(ticker or "").strip().upper() in rule.tickers)


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
        if bool(settings.get(rule.setting_key, False))
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
