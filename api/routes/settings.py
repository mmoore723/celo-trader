"""
api/routes/settings.py — Settings read/write endpoints + API credentials.
"""
from __future__ import annotations
from typing import Optional
import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from api.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/strategies")
def get_strategy_catalog_endpoint() -> dict:
    """Expose the same reviewed registry used by order routing."""
    from config import get_settings
    from config.strategy_catalog import public_strategy_catalog
    return {"strategies": public_strategy_catalog(get_settings())}


@router.get("/strategies/tested")
def get_tested_strategy_inventory() -> dict:
    from config import get_settings
    from config.strategy_inventory import tested_strategy_inventory
    return tested_strategy_inventory(get_settings())


@router.get("/strategies/history")
def get_strategy_setting_history(limit: int = 50) -> dict:
    from database import get_strategy_setting_changes
    return {"changes": get_strategy_setting_changes(limit)}


class StrategyConsentPayload(BaseModel):
    decision: str


@router.get("/strategies/recommendations")
def get_strategy_recommendations() -> dict:
    from config import get_settings
    from config.strategy_ticker_recommendations import public_recommendations
    return {"recommendations": public_recommendations(get_settings())}


@router.post("/strategies/recommendations/{strategy_id}/{ticker}")
def set_strategy_recommendation_consent(strategy_id: str, ticker: str, payload: StrategyConsentPayload) -> dict:
    from config import get_settings, save_settings
    from config.strategy_ticker_recommendations import save_user_consent, public_recommendations
    if payload.decision not in {"paper_enabled", "live_enabled", "live_pilot", "observing"}:
        raise HTTPException(400, "Decision must be paper_enabled, live_enabled, or observing")
    settings = get_settings()
    try:
        consents = save_user_consent(settings, strategy_id, ticker, payload.decision)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    save_settings({"strategy_ticker_consents": consents})
    return {"ok": True, "recommendations": public_recommendations(get_settings())}


class PublishStrategyRecommendationPayload(BaseModel):
    strategy_id: str
    ticker: str
    evidence_summary: str = Field(min_length=10)
    evidence_artifact: str = ""
    metrics: dict = Field(default_factory=dict)


@router.post("/strategies/recommendations/publish")
def publish_strategy_recommendation_endpoint(payload: PublishStrategyRecommendationPayload, request: Request) -> dict:
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(403, "Admin access required")
    from config.strategy_ticker_recommendations import publish_recommendation
    try:
        recommendation = publish_recommendation(payload.strategy_id, payload.ticker, evidence_summary=payload.evidence_summary, evidence_artifact=payload.evidence_artifact, metrics=payload.metrics)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "recommendation": recommendation}


@router.get("", response_model=Settings)
def get_settings_endpoint() -> Settings:
    from config import get_settings, get_risk_tier, MAX_CONCURRENT_POSITIONS, STARTING_CAPITAL
    from trading.tested_strategy_research import enabled_tested_research_ids
    s = get_settings()
    _risk_override = s.get("risk_per_trade")
    try:
        _risk_auto = _risk_override is None
        _balance = float(s.get("last_known_balance", STARTING_CAPITAL))
        _risk_pct = (get_risk_tier(_balance) if _risk_auto else float(_risk_override)) * 100
    except (TypeError, ValueError):
        _risk_auto, _risk_pct = True, get_risk_tier(STARTING_CAPITAL) * 100
    return Settings(
        broker_provider=str(s.get("broker_provider") or "alpaca"),
        paper_trading=bool(s.get("paper_trading", True)),
        display_timezone=str(s.get("display_timezone") or "America/New_York"),
        risk_pct=round(_risk_pct, 2),
        risk_auto=_risk_auto,
        growth_mode=bool(s.get("growth_mode", False)),
        flip_trading_enabled=bool(s.get("flip_trading_enabled", True)),
        max_concurrent_positions=int(s.get("max_concurrent_positions", MAX_CONCURRENT_POSITIONS)),
        rr_ratio_mode=str(s.get("rr_ratio_mode", "auto")),
        watchlist=list(s.get("watchlist", ["SPY"])),
        validated_strategy_ids=list(s.get("validated_strategy_ids", [])),
        strategy_orb_pullback_v2_enabled=bool(s.get("strategy_orb_pullback_v2_enabled", True)),
        strategy_spy_trend_cont_v2_enabled=bool(s.get("strategy_spy_trend_cont_v2_enabled", True)),
        strategy_spy_afternoon_fvg_v2_enabled=bool(s.get("strategy_spy_afternoon_fvg_v2_enabled", True)),
        strategy_spy_failed_range_recovery_v2_enabled=bool(s.get("strategy_spy_failed_range_recovery_v2_enabled", True)),
        strategy_tsla_two_leg_trend_pullback_v2_enabled=bool(s.get("strategy_tsla_two_leg_trend_pullback_v2_enabled", True)),
        observe_ctx_orb_nr7_inside_enabled=bool(s.get("observe_ctx_orb_nr7_inside_enabled", True)),
        observe_ctx_orb_atr10_enabled=bool(s.get("observe_ctx_orb_atr10_enabled", True)),
        observe_ctx_vwap_ker_enabled=bool(s.get("observe_ctx_vwap_ker_enabled", True)),
        observe_ctx_vwap_displacement_enabled=bool(s.get("observe_ctx_vwap_displacement_enabled", True)),
        observe_ctx_squeeze_macd_enabled=bool(s.get("observe_ctx_squeeze_macd_enabled", True)),
        research_strategy_ids=sorted(enabled_tested_research_ids(s)),
        opportunity_tier_enabled=bool(s.get("opportunity_tier_enabled", False)),
        signal_only_mode=bool(s.get("signal_only_mode", False)),
        # Trade parameters
        orb_stage1_gain_pct=float(s.get("orb_stage1_gain_pct", 50)),
        orb_stop_loss_pct=float(s.get("orb_stop_loss_pct", 20)),
        spread_gate_pct=float(s.get("spread_gate_pct", 8)),   # was stale 25, fixed 2026-07-22
        vol_roc_threshold=float(s.get("vol_roc_threshold", 0.50)),
        simplified_exit_mode=bool(s.get("simplified_exit_mode", True)),
        mtf_confirmation_enabled=bool(s.get("mtf_confirmation_enabled", True)),
        # 2026-07-24: hard-cap kill-lock threshold, was hardcoded — see risk.py
        daily_loss_hard_cap_pct=float(s.get("daily_loss_hard_cap_pct", 10.0)),
        # 2026-07-24: grade-based entry filter — see router_gates.py
        min_grade_filter_enabled=bool(s.get("min_grade_filter_enabled", False)),
        min_entry_grade=str(s.get("min_entry_grade", "C")),
        # 2026-07-24: real per-contract affordability cap, was hardcoded — see
        # trading/entry.py's "over_budget" check and scanner.py's affordability filter
        max_position_dollars_pct=float(s.get("max_position_dollars_pct", 15.0)),
    )


@router.post("", response_model=Settings)
def save_settings_endpoint(payload: Settings, request: Request) -> Settings:
    from config import get_settings, save_settings
    current = get_settings()
    data = payload.model_dump()
    target_provider = str(data.get("broker_provider") or "alpaca").lower()
    if target_provider not in {"alpaca", "tradier"}:
        raise HTTPException(400, "Broker provider must be Alpaca or Tradier")
    data["broker_provider"] = target_provider
    current_provider = str(current.get("broker_provider") or "alpaca").lower()
    current_paper = bool(current.get("paper_trading", True))
    target_paper = bool(data.get("paper_trading", current_paper))
    broker_route_changed = (
        target_provider != current_provider or target_paper != current_paper
    )
    if broker_route_changed:
        from trading.state import _get_lock
        if _get_lock(request.state.user_id).locked():
            raise HTTPException(409, "Stop the bot before changing broker or paper/live mode")
    if broker_route_changed:
        if target_provider == "tradier":
            from broker import get_tradier_broker
            broker = get_tradier_broker(paper=target_paper)[0]
            readiness = broker.readiness()
            if not readiness["ready"]:
                failures = "; ".join(
                    f"{name}: {item['detail']}"
                    for name, item in readiness["checks"].items()
                    if not item["passed"]
                )
                raise HTTPException(
                    409,
                    "Tradier cannot be activated until every read-only readiness check passes. "
                    + failures,
                )
        else:
            from broker import AlpacaClient
            broker = AlpacaClient(paper=target_paper)
        try:
            account = broker.get_account()
        except Exception as exc:
            raise HTTPException(
                409,
                f"{target_provider.title()} account could not be verified for the selected mode",
            ) from exc
        if float(account.get("equity") or 0) <= 0:
            raise HTTPException(409, f"{target_provider.title()} returned no positive account equity")
        from broker.account_identity import resolve_account_identity
        from config import get_api_keys
        keys = get_api_keys()
        identity_key = keys.get(
            (
                "tradier_api_key" if target_paper else "tradier_market_api_key"
            ) if target_provider == "tradier" else "alpaca_api_key",
            "",
        )
        data["active_broker_account_id"] = resolve_account_identity(
            identity_key, target_paper, account, provider=target_provider,
        )
        data["last_known_balance"] = float(account.get("equity") or 0)
    # Strategy promotion is evidence-controlled, not a settings-page action.
    # Keep the server's reviewed list even if a browser sends this field.
    data.pop("validated_strategy_ids", None)
    from config.strategy_catalog import REVIEWED_STRATEGIES
    for rule in REVIEWED_STRATEGIES.values():
        # Pydantic defines the complete allowlist.  Resolving catalog switches
        # generically prevents a newly reviewed control from being silently
        # dropped by an older hard-coded POST map.
        data[rule.setting_key] = bool(data.pop(rule.setting_key, False))
    from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES
    data["research_strategy_ids"] = sorted({
        str(value).strip().upper()
        for value in data.get("research_strategy_ids", [])
        if str(value).strip().upper() in TESTED_RESEARCH_STRATEGIES
    })
    # Convert risk_pct (UI %, e.g. 10.0) → risk_per_trade (decimal, e.g. 0.10).
    # get_risk_tier() reads risk_per_trade; without this conversion it never saw
    # the user's setting and always fell through to the bootstrap 5% auto-tier.
    # Both keys are saved so GET can still return risk_pct for UI display.
    _risk_auto = bool(data.pop("risk_auto", False))
    _rp_ui = data.get("risk_pct")
    if _risk_auto:
        # Do not accidentally pin an automatic tier merely because the user
        # saved an unrelated Settings change.
        data["risk_per_trade"] = None
    elif _rp_ui is not None:
        try:
            data["risk_per_trade"] = round(float(_rp_ui) / 100.0, 4)  # 10.0 → 0.10
        except (TypeError, ValueError):
            pass
    strategy_changes = [
        (
            rule.strategy_id,
            rule.setting_key,
            bool(current.get(rule.setting_key, False)),
            bool(data.get(rule.setting_key, False)),
        )
        for rule in REVIEWED_STRATEGIES.values()
        if bool(current.get(rule.setting_key, False)) != bool(data.get(rule.setting_key, False))
    ]
    current.update(data)
    save_settings(current)
    if strategy_changes:
        from database import record_strategy_setting_changes
        record_strategy_setting_changes(str(request.state.user_id), strategy_changes)

    # ── Hot-reload watchlist into the running bot ─────────────────────────────
    # Inject new pinned tickers into this user's state immediately so the bot
    # picks them up on the next tick without waiting for tomorrow's pre-market
    # scan.
    # FIX: previously wrote to the global LIVE_STATE alias (admin's state) —
    # a non-admin user saving their watchlist silently patched admin's bot
    # instead of their own. get_user_state() resolves the requesting user via
    # the auth ContextVar (already set for this request by require_auth).
    try:
        from scanner import TICKER_BLACKLIST
        new_pins = [
            t.upper().strip()
            for t in (data.get("watchlist") or [])
            if t.strip() and t.strip().upper() not in TICKER_BLACKLIST
        ]
        if new_pins:
            from trading.state import get_user_state
            _US = get_user_state()
            existing = list(_US.get("scan_watchlist") or [])
            merged   = list(dict.fromkeys(new_pins + existing))  # pins first, deduped
            _US["scan_watchlist"] = merged
            # Invalidate today's cached scan so the next full rescore includes the new tickers
            _US["scanner_ran_today"] = False
    except Exception:
        pass  # bot may not be running — non-fatal

    return payload


# ── API credentials ───────────────────────────────────────────────────────────

class CredentialsPayload(BaseModel):
    # FIX 2026-07-31: all fields now Optional — see save_credentials()'s
    # docstring for the incident this fixes. None means "the frontend didn't
    # touch this field, leave it alone"; a real (possibly empty) string
    # means "the frontend wants this exact value saved."
    alpaca_api_key:     Optional[str] = None
    alpaca_secret_key:  Optional[str] = None
    tradier_api_key:    Optional[str] = None
    tradier_market_api_key: Optional[str] = None
    tradier_account_id: Optional[str] = None
    tradier_live_account_id: Optional[str] = None


_SECRET_CREDENTIAL_FIELDS = (
    "alpaca_api_key",
    "alpaca_secret_key",
    "tradier_api_key",
    "tradier_market_api_key",
)


def _looks_like_masked_credential(value: str) -> bool:
    """Return True for a display-only secret returned by GET /credentials."""
    text = str(value or "").strip()
    return (
        text.lower() == "set"
        or "…" in text
        or "•" in text
        or "***" in text
    )


def _reject_masked_credentials(payload: CredentialsPayload) -> None:
    """Never allow a browser placeholder to replace an encrypted secret."""
    for field in _SECRET_CREDENTIAL_FIELDS:
        value = getattr(payload, field)
        if value is not None and _looks_like_masked_credential(value):
            raise HTTPException(
                400,
                f"{field} contains a masked display value. Enter the complete new credential or leave the field unchanged.",
            )


@router.get("/credentials")
def get_credentials() -> dict:
    """
    Return stored API keys for the current user — secrets are MASKED for display.
    Frontend uses this to show which keys are set without revealing the full value.
    """
    from config import get_api_keys
    keys = get_api_keys()
    def mask(v: str) -> str:
        return v[:4] + "…" + v[-4:] if len(v) >= 10 else ("set" if v else "")
    return {
        "alpaca_api_key":     mask(keys.get("alpaca_api_key", "")),
        "alpaca_secret_key":  mask(keys.get("alpaca_secret_key", "")),
        "tradier_api_key":    mask(keys.get("tradier_api_key", "")),
        "tradier_market_api_key": mask(keys.get("tradier_market_api_key", "")),
        "tradier_account_id": keys.get("tradier_account_id", ""),   # not secret
        "tradier_live_account_id": keys.get("tradier_live_account_id", ""),
        "has_alpaca":         bool(keys.get("alpaca_api_key")),
        "has_tradier":        bool(keys.get("tradier_api_key")),
        "has_tradier_market": bool(keys.get("tradier_market_api_key")),
        "has_tradier_live_account": bool(keys.get("tradier_live_account_id")),
    }


@router.post("/credentials")
def save_credentials(payload: CredentialsPayload, request: Request) -> dict:
    """
    Save Alpaca + Tradier API keys for the current user (encrypted at rest).
    Note: Alpaca uses the SAME key pair for both paper and live trading.
    The paper vs live routing is controlled by the Paper/Live toggle, not the keys.

    FIX 2026-07-31 — real incident: GET /credentials returns MASKED display
    values (e.g. "abcd…wxyz"), which the Settings.tsx form loads as its
    initial state. The old code here always saved ALL FOUR fields
    unconditionally, so editing only the Alpaca keys silently re-saved the
    Tradier key AS its own masked display string — replacing a real
    credential with garbage. That triggered 268 silent Tradier 401s across
    every ticker with zero visible indication anywhere. Fix, two parts:
      1. CredentialsPayload fields are now Optional — None means "the
         frontend didn't touch this field" (see Settings.tsx's matching
         dirty-tracking fix, which now only sends touched fields).
      2. save_api_keys() is a full-overwrite primitive (encrypts exactly
         the dict it's given), so we read-merge existing keys first —
         otherwise a partial payload would DELETE the untouched keys
         instead of leaving them alone.
    """
    from trading.state import _get_lock
    if _get_lock(request.state.user_id).locked():
        raise HTTPException(
            409,
            "Stop the bot before changing broker credentials so one session cannot span two accounts.",
        )

    # Defense in depth for older/cached frontends and password-manager
    # autofill. The current UI never submits a stored mask, but the API must
    # independently guarantee that display-only text cannot become a secret.
    _reject_masked_credentials(payload)

    from config import get_api_keys, save_api_keys
    current = get_api_keys()
    verified_tradier_market = False
    if payload.alpaca_api_key is not None:
        current["alpaca_api_key"] = payload.alpaca_api_key.strip()
    if payload.alpaca_secret_key is not None:
        current["alpaca_secret_key"] = payload.alpaca_secret_key.strip()
    if payload.tradier_api_key is not None:
        current["tradier_api_key"] = payload.tradier_api_key.strip()
    if payload.tradier_market_api_key is not None:
        candidate_market_token = payload.tradier_market_api_key.strip()
        if candidate_market_token:
            from broker.credential_validation import validate_tradier_market_token
            validation = validate_tradier_market_token(candidate_market_token)
            if not validation["ok"]:
                status = 400 if validation["code"] in {"missing", "unauthorized"} else 503
                raise HTTPException(status, validation["detail"])
            verified_tradier_market = True
        current["tradier_market_api_key"] = candidate_market_token
    if payload.tradier_account_id is not None:
        current["tradier_account_id"] = payload.tradier_account_id.strip()
    if payload.tradier_live_account_id is not None:
        current["tradier_live_account_id"] = payload.tradier_live_account_id.strip()
    if bool(current.get("alpaca_api_key")) != bool(current.get("alpaca_secret_key")):
        raise HTTPException(400, "Alpaca API key and secret key must be saved together")
    if bool(current.get("tradier_api_key")) != bool(current.get("tradier_account_id")):
        raise HTTPException(400, "Tradier API key and account ID must be saved together")
    alpaca_changed = payload.alpaca_api_key is not None or payload.alpaca_secret_key is not None
    tradier_changed = (
        payload.tradier_api_key is not None
        or payload.tradier_market_api_key is not None
        or payload.tradier_account_id is not None
        or payload.tradier_live_account_id is not None
    )
    save_api_keys(current)
    from broker import configured_broker_provider
    provider = configured_broker_provider()
    active_broker_changed = alpaca_changed if provider == "alpaca" else tradier_changed
    if not active_broker_changed:
        return {
            "ok": True,
            "message": (
                "Tradier real-time pricing verified and API keys saved securely"
                if verified_tradier_market else "API keys saved securely"
            ),
        }

    # A key can point at a completely different Alpaca account.  Local paper
    # history is not broker-owned, so it must be explicitly scoped rather than
    # silently presented as this newly connected account's performance.
    from config import get_settings, save_settings, get_bot_state_path
    from broker.account_identity import resolve_account_identity
    settings = get_settings()
    paper = bool(settings.get("paper_trading", True))
    account: dict | None = None
    try:
        if provider == "tradier":
            from broker import get_tradier_broker
            account = get_tradier_broker()[0].get_account()
        else:
            from broker import AlpacaClient
            account = AlpacaClient().get_account()
    except Exception:
        # A bad/new key should still isolate old local results. The fallback is
        # a one-way hash of the key id, never the secret or raw key.
        pass
    identity_key = (
        current.get("tradier_api_key" if paper else "tradier_market_api_key", "")
        if provider == "tradier" else current.get("alpaca_api_key", "")
    )
    identity = resolve_account_identity(
        identity_key, paper, account, provider=provider,
    )
    previous_identity = str(settings.get("active_broker_account_id") or "")
    changed_account = identity != previous_identity
    if changed_account:
        from trading.state import _now_et
        save_settings({
            "active_broker_account_id": identity,
            "last_known_balance": 0.0,
            f"day_start_{_now_et().date().isoformat()}": 0.0,
        })
        # Clear persisted display state immediately. A running loop retains its
        # old in-memory client, so it is intentionally NOT restarted here: an
        # automatic stop could abandon management of an open position. The UI
        # tells the user to stop/start after saving instead.
        try:
            state_path = get_bot_state_path()
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            state.update({
                "broker_account_id": identity,
                "account_balance": 0.0,
                "day_start_balance": 0.0,
                "session_pnl": 0.0,
                "credentials_restart_required": True,
            })
            from config import atomic_write_json
            atomic_write_json(state_path, state)
        except Exception:
            pass
    return {
        "ok": True,
        "message": (
            f"{provider.title()} account changed. Historical results are now scoped to the new account. "
            "Stop and start the bot before trading so it reconnects with the new key."
            if changed_account else f"{provider.title()} keys saved securely. Stop and start the bot before trading so it reconnects."
        ),
    }


@router.get("/broker-readiness")
def broker_readiness(paper: Optional[bool] = None) -> dict:
    """Run read-only cutover checks; this endpoint can never submit an order."""
    from broker import configured_broker_provider, get_tradier_broker
    provider = configured_broker_provider()
    result = get_tradier_broker(paper=paper)[0].readiness()
    result["selected_provider"] = provider
    return result


@router.get("/connection-health")
def connection_health(request: Request) -> dict:
    """Return a fresh, read-only broker/API audit without exposing tokens."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(401, "Authenticated user context is missing")
    from config import get_api_keys, get_settings
    from broker.connection_health import get_connection_health
    return get_connection_health(
        get_settings(user_id=str(user_id)),
        get_api_keys(user_id=str(user_id)),
    )
