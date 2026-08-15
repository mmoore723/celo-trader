"""
api/routes/settings.py — Settings read/write endpoints + API credentials.
"""
from __future__ import annotations
from typing import Optional
import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from api.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/strategies")
def get_strategy_catalog_endpoint() -> dict:
    """Expose the same reviewed registry used by order routing."""
    from config import get_settings
    from config.strategy_catalog import public_strategy_catalog
    return {"strategies": public_strategy_catalog(get_settings())}


@router.get("/strategies/history")
def get_strategy_setting_history(limit: int = 50) -> dict:
    from database import get_strategy_setting_changes
    return {"changes": get_strategy_setting_changes(limit)}


@router.get("", response_model=Settings)
def get_settings_endpoint() -> Settings:
    from config import get_settings, get_risk_tier, MAX_CONCURRENT_POSITIONS, STARTING_CAPITAL
    s = get_settings()
    _risk_override = s.get("risk_per_trade")
    try:
        _risk_auto = _risk_override is None
        _balance = float(s.get("last_known_balance", STARTING_CAPITAL))
        _risk_pct = (get_risk_tier(_balance) if _risk_auto else float(_risk_override)) * 100
    except (TypeError, ValueError):
        _risk_auto, _risk_pct = True, get_risk_tier(STARTING_CAPITAL) * 100
    return Settings(
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
        strategy_tsla_two_leg_trend_pullback_v2_enabled=bool(s.get("strategy_tsla_two_leg_trend_pullback_v2_enabled", True)),
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
    # Strategy promotion is evidence-controlled, not a settings-page action.
    # Keep the server's reviewed list even if a browser sends this field.
    data.pop("validated_strategy_ids", None)
    data["strategy_orb_pullback_v2_enabled"] = data.pop("strategy_orb_pullback_v2_enabled", False)
    data["strategy_spy_trend_cont_v2_enabled"] = data.pop("strategy_spy_trend_cont_v2_enabled", False)
    data["strategy_spy_afternoon_fvg_v2_enabled"] = data.pop("strategy_spy_afternoon_fvg_v2_enabled", False)
    data["strategy_tsla_two_leg_trend_pullback_v2_enabled"] = data.pop("strategy_tsla_two_leg_trend_pullback_v2_enabled", False)
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
    from config.strategy_catalog import REVIEWED_STRATEGIES
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
    tradier_account_id: Optional[str] = None


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
        "tradier_account_id": keys.get("tradier_account_id", ""),   # not secret
        "has_alpaca":         bool(keys.get("alpaca_api_key")),
        "has_tradier":        bool(keys.get("tradier_api_key")),
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

    from config import get_api_keys, save_api_keys
    current = get_api_keys()
    if payload.alpaca_api_key is not None:
        current["alpaca_api_key"] = payload.alpaca_api_key.strip()
    if payload.alpaca_secret_key is not None:
        current["alpaca_secret_key"] = payload.alpaca_secret_key.strip()
    if payload.tradier_api_key is not None:
        current["tradier_api_key"] = payload.tradier_api_key.strip()
    if payload.tradier_account_id is not None:
        current["tradier_account_id"] = payload.tradier_account_id.strip()
    if bool(current.get("alpaca_api_key")) != bool(current.get("alpaca_secret_key")):
        raise HTTPException(400, "Alpaca API key and secret key must be saved together")
    if bool(current.get("tradier_api_key")) != bool(current.get("tradier_account_id")):
        raise HTTPException(400, "Tradier API key and account ID must be saved together")
    alpaca_changed = payload.alpaca_api_key is not None or payload.alpaca_secret_key is not None
    save_api_keys(current)
    if not alpaca_changed:
        return {"ok": True, "message": "API keys saved securely"}

    # A key can point at a completely different Alpaca account.  Local paper
    # history is not broker-owned, so it must be explicitly scoped rather than
    # silently presented as this newly connected account's performance.
    from config import get_settings, save_settings, get_bot_state_path
    from broker.account_identity import resolve_account_identity
    settings = get_settings()
    paper = bool(settings.get("paper_trading", True))
    account: dict | None = None
    try:
        from broker import AlpacaClient
        account = AlpacaClient().get_account()
    except Exception:
        # A bad/new key should still isolate old local results. The fallback is
        # a one-way hash of the key id, never the secret or raw key.
        pass
    identity = resolve_account_identity(current.get("alpaca_api_key", ""), paper, account)
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
            "Alpaca account changed. Historical results are now scoped to the new account. "
            "Stop and start the bot before trading so it reconnects with the new key."
            if changed_account else "Alpaca keys saved securely. Stop and start the bot before trading so it reconnects."
        ),
    }
