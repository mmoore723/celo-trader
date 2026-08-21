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


def publish_recommendation(strategy_id: str, ticker: str, *, evidence_summary: str, evidence_artifact: str = "", metrics: dict | None = None) -> dict:
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    sid, symbol = strategy_id.strip().upper(), ticker.strip().upper()
    if sid not in REVIEWED_STRATEGIES:
        raise ValueError("Unknown reviewed strategy")
    if sid in reviewed_strategy_integrity_errors():
        raise ValueError("Strategy integrity review is not current")
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise ValueError("Invalid ticker")
    if symbol in REVIEWED_STRATEGIES[sid].tickers:
        raise ValueError("This ticker is already in the strategy's current approved scope")
    row = {
        "strategy_id": sid, "ticker": symbol,
        "strategy_version": REVIEWED_STRATEGIES[sid].version,
        "status": "published", "evidence_summary": evidence_summary.strip(),
        "evidence_artifact": evidence_artifact.strip(), "metrics": metrics or {},
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    rows = [item for item in load_recommendations() if pair_key(item.get("strategy_id"), item.get("ticker")) != pair_key(sid, symbol)]
    rows.append(row)
    RECOMMENDATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(RECOMMENDATIONS_PATH, {"recommendations": rows})
    return row


def publish_qualified_recommendation(qualification: dict, *, evidence_artifact: str) -> dict:
    """Publish only the exact version that passed the causal qualifier.

    This is the automation boundary.  The nightly worker cannot turn a user
    strategy on; it can only make a reviewed recommendation available for
    that user's separate paper/live consent.
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
        },
    )


def consent_for(settings: dict, strategy_id: object, ticker: object) -> ConsentDecision:
    consents = settings.get(CONSENT_SETTINGS_KEY, {})
    value = consents.get(pair_key(strategy_id, ticker)) if isinstance(consents, dict) else None
    return value if value in {"paper_enabled", "live_enabled"} else "observing"


def save_user_consent(settings: dict, strategy_id: object, ticker: object, decision: ConsentDecision) -> dict:
    if decision not in {"paper_enabled", "live_enabled", "observing"}:
        raise ValueError("Invalid consent decision")
    recommendation = published_recommendation(strategy_id, ticker)
    if recommendation is None:
        raise ValueError("This strategy/ticker recommendation is not published")
    if decision == "live_enabled":
        from config.strategy_catalog import REVIEWED_STRATEGIES
        rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
        if rule is None or rule.paper_only:
            raise ValueError("This strategy has not been promoted for live-money use")
    consents = dict(settings.get(CONSENT_SETTINGS_KEY, {}) or {})
    consents[pair_key(strategy_id, ticker)] = decision
    return consents


def public_recommendations(settings: dict) -> list[dict]:
    from config.strategy_catalog import REVIEWED_STRATEGIES
    result = []
    for row in load_recommendations():
        sid, ticker = str(row.get("strategy_id", "")).upper(), str(row.get("ticker", "")).upper()
        rule = REVIEWED_STRATEGIES.get(sid)
        if not rule or row.get("status") != "published" or ticker in rule.tickers:
            continue
        consents = settings.get(CONSENT_SETTINGS_KEY, {})
        has_decision = isinstance(consents, dict) and pair_key(sid, ticker) in consents
        decision = consent_for(settings, sid, ticker) if has_decision else "pending"
        result.append({
            **row,
            "display_name": rule.display_name,
            "decision": decision,
            "paper_enabled": decision == "paper_enabled",
            "live_enabled": decision == "live_enabled",
            "live_eligible": not rule.paper_only,
            "account_mode": "paper" if bool(settings.get("paper_trading", True)) else "live",
        })
    return result


def is_user_authorized_ticker(strategy_id: object, ticker: object, settings: dict) -> bool:
    """Preserve static defaults; dynamic approvals are mode-specific and fail closed."""
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    sid, symbol = str(strategy_id or "").strip().upper(), str(ticker or "").strip().upper()
    rule = REVIEWED_STRATEGIES.get(sid)
    if not rule or sid in reviewed_strategy_integrity_errors():
        return False
    # Reviewed V2 strategies are paper-only regardless of whether the ticker
    # came from the original scope or a later recommendation.
    if rule.paper_only and not bool(settings.get("paper_trading", True)):
        return False
    if symbol in rule.tickers:
        return True
    recommendation = published_recommendation(sid, symbol)
    if not recommendation or recommendation.get("strategy_version") != rule.version:
        return False
    required_consent = "paper_enabled" if bool(settings.get("paper_trading", True)) else "live_enabled"
    return consent_for(settings, sid, symbol) == required_consent


def approved_dynamic_tickers(settings: dict, enabled_strategy_ids: object = ()) -> list[str]:
    """Return extra tickers this account explicitly enabled in its current mode."""
    enabled = {str(value or "").strip().upper() for value in (enabled_strategy_ids or ())}
    tickers: set[str] = set()
    for row in load_recommendations():
        sid = str(row.get("strategy_id", "")).strip().upper()
        ticker = str(row.get("ticker", "")).strip().upper()
        if enabled and sid not in enabled:
            continue
        if is_user_authorized_ticker(sid, ticker, settings):
            tickers.add(ticker)
    return sorted(tickers)
