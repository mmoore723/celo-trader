"""Shared strategy/ticker evidence with account- and mode-scoped consent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from config.atomic_files import atomic_write_json
from config.paths import BASE_DIR

ConsentDecision = Literal["paper_enabled", "live_enabled", "observing"]
RECOMMENDATIONS_PATH = BASE_DIR / "data" / "strategy_ticker_recommendations.json"
CONSENT_SETTINGS_KEY = "strategy_ticker_consents"


def pair_key(strategy_id: object, ticker: object) -> str:
    return f"{str(strategy_id or '').strip().upper()}:{str(ticker or '').strip().upper()}"


def load_recommendations() -> list[dict]:
    try:
        payload = json.loads(RECOMMENDATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("recommendations", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def published_recommendation(strategy_id: object, ticker: object) -> dict | None:
    wanted = pair_key(strategy_id, ticker)
    return next((row for row in load_recommendations() if pair_key(row.get("strategy_id"), row.get("ticker")) == wanted and row.get("status") == "published"), None)


def _is_current_qualified_recommendation(strategy_id: object, ticker: object) -> bool:
    """Fail closed unless forward evidence matches the current catalog version."""
    from config.strategy_catalog import REVIEWED_STRATEGIES

    sid = str(strategy_id or "").strip().upper()
    rule = REVIEWED_STRATEGIES.get(sid)
    recommendation = published_recommendation(sid, ticker)
    return bool(
        rule and recommendation
        and recommendation.get("strategy_version") == rule.version
        and recommendation.get("qualification_verified") is True
    )


def publish_recommendation(strategy_id: str, ticker: str, *, evidence_summary: str, evidence_artifact: str = "", metrics: dict | None = None, qualification_verified: bool = False) -> dict:
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    sid, symbol = strategy_id.strip().upper(), ticker.strip().upper()
    if sid not in REVIEWED_STRATEGIES:
        raise ValueError("Unknown reviewed strategy")
    if sid in reviewed_strategy_integrity_errors():
        raise ValueError("Strategy integrity review is not current")
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise ValueError("Invalid ticker")
    # A recommendation is also the user-consent boundary for an original
    # reviewed ticker.  Historical scope must never silently become live order
    # authority, so base pairs and newly discovered pairs use the same record.
    row = {
        "strategy_id": sid, "ticker": symbol,
        "strategy_version": REVIEWED_STRATEGIES[sid].version,
        "status": "published", "evidence_summary": evidence_summary.strip(),
        "evidence_artifact": evidence_artifact.strip(), "metrics": metrics or {},
        "qualification_verified": bool(qualification_verified),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    rows = [item for item in load_recommendations() if pair_key(item.get("strategy_id"), item.get("ticker")) != pair_key(sid, symbol)]
    rows.append(row)
    RECOMMENDATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(RECOMMENDATIONS_PATH, {"recommendations": rows})
    return row


def publish_qualified_recommendation(qualification: dict, *, evidence_artifact: str) -> dict:
    """Publish only the exact version that passed the causal qualifier.

    This is the automation boundary. The nightly worker cannot turn a user
    strategy on; it can only publish a recommendation. A live-connected
    account may observe it without placing an order, and only that account
    owner may later grant live order authority.
    """
    from config.strategy_catalog import REVIEWED_STRATEGIES

    if qualification.get("decision") != "qualified":
        raise ValueError("Only qualified evidence may become a recommendation")
    sid = str(qualification.get("strategy_id") or "").strip().upper()
    ticker = str(qualification.get("ticker") or "").strip().upper()
    rule = REVIEWED_STRATEGIES.get(sid)
    if rule is None or qualification.get("strategy_version") != rule.version:
        raise ValueError("Qualification does not match the current strategy version")
    training = qualification.get("training") or {}
    holdout = qualification.get("holdout") or {}
    summary = (
        f"Forward holdout qualified {ticker}: training PF {training.get('profit_factor')}, "
        f"holdout PF {holdout.get('profit_factor')} across "
        f"{holdout.get('trading_days', 0)} holdout trading days."
    )
    return publish_recommendation(
        sid, ticker, evidence_summary=summary,
        evidence_artifact=evidence_artifact, metrics={
            "training": training,
            "holdout": holdout,
            "holdout_start": qualification.get("holdout_start"),
            "strategy_version": rule.version,
        }, qualification_verified=True,
    )


def consent_for(settings: dict, strategy_id: object, ticker: object) -> ConsentDecision:
    consents = settings.get(CONSENT_SETTINGS_KEY, {})
    value = consents.get(pair_key(strategy_id, ticker)) if isinstance(consents, dict) else None
    # Migrate the former pilot choice to ordinary live enablement. Research
    # qualification and per-user consent remain required, but an approved
    # strategy is no longer subject to an artificial one-contract rollout.
    if value == "live_pilot":
        return "live_enabled"
    return value if value in {"paper_enabled", "live_enabled"} else "observing"


def save_user_consent(settings: dict, strategy_id: object, ticker: object, decision: ConsentDecision) -> dict:
    if decision == "live_pilot":  # backward-compatible API migration
        decision = "live_enabled"
    if decision not in {"paper_enabled", "live_enabled", "observing"}:
        raise ValueError("Invalid consent decision")
    recommendation = published_recommendation(strategy_id, ticker)
    if recommendation is None:
        raise ValueError("This strategy/ticker recommendation is not published")
    if decision in {"paper_enabled", "live_enabled"} and not _is_current_qualified_recommendation(strategy_id, ticker):
        raise ValueError("This strategy/ticker match has not passed forward qualification")
    if decision == "live_enabled":
        from config.strategy_catalog import REVIEWED_STRATEGIES
        from config.strategy_live_promotion import review_live_promotion
        rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
        if (
            rule is None
            or not bool(recommendation.get("qualification_verified"))
            or not review_live_promotion(rule, str(ticker or "").strip().upper()).ready
        ):
            raise ValueError("This strategy has not been promoted for live-money use")
    consents = dict(settings.get(CONSENT_SETTINGS_KEY, {}) or {})
    consents[pair_key(strategy_id, ticker)] = decision
    return consents


def public_recommendations(settings: dict) -> list[dict]:
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from config.strategy_live_promotion import review_live_promotion
    result = []
    for row in load_recommendations():
        sid, ticker = str(row.get("strategy_id", "")).upper(), str(row.get("ticker", "")).upper()
        rule = REVIEWED_STRATEGIES.get(sid)
        if not rule or row.get("status") != "published":
            continue
        consents = settings.get(CONSENT_SETTINGS_KEY, {})
        has_decision = isinstance(consents, dict) and pair_key(sid, ticker) in consents
        decision = consent_for(settings, sid, ticker) if has_decision else "pending"
        live_eligible = bool(
            row.get("qualification_verified")
            and review_live_promotion(rule, ticker).ready
        )
        rollout_stage = (
            "live_enabled"
            if decision == "live_enabled"
            else "paper_enabled"
            if decision == "paper_enabled"
            else "approval_needed"
            if bool(row.get("qualification_verified"))
            else "observing"
        )
        result.append({
            **row,
            "display_name": rule.display_name,
            "decision": decision,
            "paper_enabled": decision == "paper_enabled",
            "live_enabled": decision == "live_enabled",
            "live_eligible": live_eligible,
            "validation_state": (
                "qualified_for_live" if live_eligible else "shadow_observation"
            ),
            # Human-facing rollout state.  "Observing" describes an analysis
            # lane, not an Alpaca account mode; a live-connected account stays
            # live throughout this process.
            "rollout_stage": rollout_stage,
            "observation_requires_paper_mode": False,
            "account_mode": "paper" if bool(settings.get("paper_trading", True)) else "live",
        })
    return result


def is_paper_enabled_pair(strategy_id: object, ticker: object, settings: dict) -> bool:
    """Allow a research rule into paper only after evidence and user consent."""
    if not bool(settings.get("paper_trading", True)):
        return False
    return bool(
        _is_current_qualified_recommendation(strategy_id, ticker)
        and consent_for(settings, strategy_id, ticker) == "paper_enabled"
    )


def has_user_paper_enabled(strategy_id: object, settings: dict) -> bool:
    """Return whether this paper account approved any qualified ticker pair."""
    sid = str(strategy_id or "").strip().upper()
    if not bool(settings.get("paper_trading", True)):
        return False
    return any(
        str(row.get("strategy_id", "")).strip().upper() == sid
        and is_paper_enabled_pair(sid, row.get("ticker"), settings)
        for row in load_recommendations()
    )


def is_user_authorized_ticker(strategy_id: object, ticker: object, settings: dict) -> bool:
    """Preserve static defaults; dynamic approvals are mode-specific and fail closed."""
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    sid, symbol = str(strategy_id or "").strip().upper(), str(ticker or "").strip().upper()
    rule = REVIEWED_STRATEGIES.get(sid)
    if not rule or sid in reviewed_strategy_integrity_errors():
        return False
    mode = "paper" if bool(settings.get("paper_trading", True)) else "live"
    from strategy_health.pair_recommendations import consent_scope
    key = consent_scope(settings, sid, symbol)
    if (settings.get("strategy_pair_pauses") or {}).get(key) is True:
        return False
    grant = (settings.get("strategy_pair_approvals") or {}).get(key) or {}
    if grant.get("strategy_version") == rule.version and grant.get("user_approved") is True:
        if rule.authored_exit_order_route:
            return symbol in rule.recommendation_tickers and grant.get("strategy_id") == sid and grant.get("ticker") == symbol
        if mode == "paper":
            return not rule.observation_only
        from config.strategy_live_promotion import review_live_promotion
        return not rule.observation_only and review_live_promotion(rule, symbol).ready
    if symbol in rule.tickers:
        # Existing reviewed pairs are controlled by this user's ordinary
        # strategy switch in both paper and live mode. Consent prompts are for
        # future ticker/strategy matches which are outside this static scope.
        return (
            bool(settings.get("paper_trading", True))
            or not rule.paper_only
            or is_live_enabled_pair(sid, symbol, settings)
        )
    recommendation = published_recommendation(sid, symbol)
    if not recommendation or recommendation.get("strategy_version") != rule.version:
        return False
    if bool(settings.get("paper_trading", True)):
        return consent_for(settings, sid, symbol) == "paper_enabled"
    # Dynamic live authority is narrower than static catalog authority: it is
    # granted only to this qualified pair and this consenting account.
    return is_live_enabled_pair(sid, symbol, settings)


def is_live_enabled_pair(strategy_id: object, ticker: object, settings: dict) -> bool:
    """Return true only for a fully reviewed, user-approved dynamic live pair."""
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    from config.strategy_live_promotion import review_live_promotion

    sid, symbol = str(strategy_id or "").strip().upper(), str(ticker or "").strip().upper()
    rule = REVIEWED_STRATEGIES.get(sid)
    if (
        bool(settings.get("paper_trading", True))
        or not rule
        or sid in reviewed_strategy_integrity_errors()
        or (not rule.authored_exit_order_route and not review_live_promotion(rule, symbol).ready)
    ):
        return False
    from strategy_health.pair_recommendations import consent_scope
    scope = consent_scope(settings, sid, symbol)
    if (settings.get("strategy_pair_pauses") or {}).get(scope) is True:
        return False
    grant = (settings.get("strategy_pair_approvals") or {}).get(scope) or {}
    if grant.get("strategy_version") == rule.version and grant.get("user_approved") is True:
        if rule.authored_exit_order_route:
            return symbol in rule.recommendation_tickers and grant.get("strategy_id") == sid and grant.get("ticker") == symbol
        return not rule.observation_only
    recommendation = published_recommendation(sid, symbol)
    return bool(
        recommendation
        and recommendation.get("strategy_version") == rule.version
        and recommendation.get("qualification_verified") is True
        and consent_for(settings, sid, symbol) == "live_enabled"
    )


def has_user_live_enabled(strategy_id: object, settings: dict) -> bool:
    """Return true when this live account authorized at least one exact dynamic pair."""
    sid = str(strategy_id or "").strip().upper()
    if bool(settings.get("paper_trading", True)):
        return False
    if any(grant.get("strategy_id") == sid and is_live_enabled_pair(sid, grant.get("ticker"), settings)
           for grant in (settings.get("strategy_pair_approvals") or {}).values()):
        return True
    return any(
        str(row.get("strategy_id", "")).strip().upper() == sid
        and is_live_enabled_pair(sid, row.get("ticker"), settings)
        for row in load_recommendations()
    )


def approved_dynamic_tickers(settings: dict, enabled_strategy_ids: object = ()) -> list[str]:
    """Return extra tickers this account explicitly enabled in its current mode."""
    enabled = {str(value or "").strip().upper() for value in (enabled_strategy_ids or ())}
    tickers: set[str] = set()
    for grant in (settings.get("strategy_pair_approvals") or {}).values():
        sid, ticker = grant.get("strategy_id"), grant.get("ticker")
        if sid and ticker and (not enabled or sid in enabled) and is_user_authorized_ticker(sid, ticker, settings):
            tickers.add(ticker)
    for row in load_recommendations():
        sid = str(row.get("strategy_id", "")).strip().upper()
        ticker = str(row.get("ticker", "")).strip().upper()
        if enabled and sid not in enabled:
            continue
        if is_user_authorized_ticker(sid, ticker, settings):
            tickers.add(ticker)
    return sorted(tickers)
