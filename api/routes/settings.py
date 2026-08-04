"""
api/routes/settings.py — Settings read/write endpoints + API credentials.
"""
from __future__ import annotations
from typing import Optional
from datetime import date
import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from api.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
        # No strategy is enabled by default. A promotion must set its flag
        # deliberately after it survives real option quote validation.
        orb_enabled=bool(s.get("strategy_orb_enabled", False)),
        vwap_pullback_enabled=bool(s.get("strategy_vwap_enabled", False)),
        fvg_enabled=bool(s.get("strategy_fvg_enabled", False)),
        # IFVG — wired 2026-07-18. Was previously missing from both this GET
        # endpoint and the POST mapping below, so the Settings.ifvg_enabled
        # model field (defaults True) was never actually read from or saved
        # to storage; entry.py's enable-flag tuple also lacked an entry for
        # it, so the strategy could never fire regardless of this field.
        ifvg_enabled=bool(s.get("strategy_ifvg_enabled", False)),
        bos_mss_enabled=bool(s.get("strategy_bos_enabled", False)),
        chan_break_enabled=bool(s.get("strategy_chan_enabled", False)),
        mid_brk_enabled=bool(s.get("strategy_mid_enabled", False)),  # research hold; see Settings/Playbooks
        trend_cont_enabled=bool(s.get("strategy_tcont_enabled", False)),
        # AFT_REV — added to Settings 2026-07-20. Previously had NO field in
        # this model or endpoint at all, so it could never be toggled from
        # the UI regardless of what entry.py's default said. Re-enabled for
        # the same reason as VWAP_PB — its -$127/trade (0-for-4) audit
        # predates the trade-recording fixes.
        aft_rev_enabled=bool(s.get("strategy_aft_enabled", False)),
        gap_go_enabled=bool(s.get("strategy_gapgo_enabled", False)),
        liquidity_sweep_enabled=bool(s.get("strategy_liqsweep_enabled", False)),
        opportunity_tier_enabled=bool(s.get("opportunity_tier_enabled", False)),
        signal_only_mode=bool(s.get("signal_only_mode", False)),
        # Trade parameters
        orb_stage1_gain_pct=float(s.get("orb_stage1_gain_pct", 50)),
        orb_stop_loss_pct=float(s.get("orb_stop_loss_pct", 20)),
        spread_gate_pct=float(s.get("spread_gate_pct", 8)),   # was stale 25, fixed 2026-07-22
        vol_roc_threshold=float(s.get("vol_roc_threshold", 0.50)),
        simplified_exit_mode=bool(s.get("simplified_exit_mode", True)),
        mtf_confirmation_enabled=bool(s.get("mtf_confirmation_enabled", True)),
        # 2026-07-31: INST_ORB immediate-entry (no-retest) toggle — see
        # strategies/inst_orb.py and api/models.py's field comment.
        inst_orb_immediate_entry_enabled=bool(s.get("strategy_instorb_immediate_entry", False)),
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
def save_settings_endpoint(payload: Settings) -> Settings:
    from config import get_settings, save_settings
    current = get_settings()
    data = payload.model_dump()
    # Strategy promotion is evidence-controlled, not a settings-page action.
    # Keep the server's reviewed list even if a browser sends this field.
    data.pop("validated_strategy_ids", None)
    # Map all frontend field names → strategy_*_enabled keys that entry.py reads
    data["strategy_orb_enabled"]   = data.pop("orb_enabled", False)
    data["strategy_vwap_enabled"]  = data.pop("vwap_pullback_enabled", False)
    data["strategy_fvg_enabled"]   = data.pop("fvg_enabled", False)
    data["strategy_ifvg_enabled"]  = data.pop("ifvg_enabled", False)
    data["strategy_bos_enabled"]   = data.pop("bos_mss_enabled", False)
    data["strategy_chan_enabled"]   = data.pop("chan_break_enabled", False)
    data["strategy_mid_enabled"]    = data.pop("mid_brk_enabled", False)
    data["strategy_tcont_enabled"]  = data.pop("trend_cont_enabled", False)
    data["strategy_aft_enabled"]    = data.pop("aft_rev_enabled", False)
    data["strategy_gapgo_enabled"]  = data.pop("gap_go_enabled", False)
    data["strategy_liqsweep_enabled"] = data.pop("liquidity_sweep_enabled", False)
    data["strategy_instorb_immediate_entry"] = data.pop("inst_orb_immediate_entry_enabled", False)
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
    current.update(data)
    save_settings(current)

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
def save_credentials(payload: CredentialsPayload) -> dict:
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
        save_settings({
            "active_broker_account_id": identity,
            "last_known_balance": 0.0,
            f"day_start_{date.today().isoformat()}": 0.0,
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
            state_path.write_text(json.dumps(state, indent=2, default=str))
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
