"""
api/routes/settings.py — Settings read/write endpoints + API credentials.
"""
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from api.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings_endpoint() -> Settings:
    from config import get_settings
    s = get_settings()
    return Settings(
        risk_pct=float(s.get("risk_pct", 1.0)),
        growth_mode=bool(s.get("growth_mode", False)),
        flip_trading_enabled=bool(s.get("flip_trading_enabled", True)),
        max_concurrent_positions=int(s.get("max_concurrent_positions", 1)),
        rr_ratio_mode=str(s.get("rr_ratio_mode", "dynamic")),
        watchlist=list(s.get("watchlist", ["SPY"])),
        # All strategy flags use the strategy_*_enabled keys that entry.py reads
        orb_enabled=bool(s.get("strategy_orb_enabled", True)),
        vwap_pullback_enabled=bool(s.get("strategy_vwap_enabled", True)),
        fvg_enabled=bool(s.get("strategy_fvg_enabled", True)),
        bos_mss_enabled=bool(s.get("strategy_bos_enabled", True)),
        chan_break_enabled=bool(s.get("strategy_chan_enabled", True)),
        mid_brk_enabled=bool(s.get("strategy_mid_enabled", True)),
        trend_cont_enabled=bool(s.get("strategy_tcont_enabled", True)),
        signal_only_mode=bool(s.get("signal_only_mode", False)),
        # Trade parameters
        orb_stage1_gain_pct=float(s.get("orb_stage1_gain_pct", 50)),
        orb_stop_loss_pct=float(s.get("orb_stop_loss_pct", 20)),
        spread_gate_pct=float(s.get("spread_gate_pct", 25)),
        vol_roc_threshold=float(s.get("vol_roc_threshold", 0.50)),
    )


@router.post("", response_model=Settings)
def save_settings_endpoint(payload: Settings) -> Settings:
    from config import get_settings, save_settings
    current = get_settings()
    data = payload.model_dump()
    # Map all frontend field names → strategy_*_enabled keys that entry.py reads
    data["strategy_orb_enabled"]   = data.pop("orb_enabled", True)
    data["strategy_vwap_enabled"]  = data.pop("vwap_pullback_enabled", True)
    data["strategy_fvg_enabled"]   = data.pop("fvg_enabled", True)
    data["strategy_bos_enabled"]   = data.pop("bos_mss_enabled", True)
    data["strategy_chan_enabled"]   = data.pop("chan_break_enabled", True)
    data["strategy_mid_enabled"]    = data.pop("mid_brk_enabled", True)
    data["strategy_tcont_enabled"]  = data.pop("trend_cont_enabled", True)
    current.update(data)
    save_settings(current)

    # ── Hot-reload watchlist into the running bot ─────────────────────────────
    # Inject new pinned tickers into LIVE_STATE immediately so the bot picks
    # them up on the next tick without waiting for tomorrow's pre-market scan.
    try:
        from scanner import TICKER_BLACKLIST
        new_pins = [
            t.upper().strip()
            for t in (data.get("watchlist") or [])
            if t.strip() and t.strip().upper() not in TICKER_BLACKLIST
        ]
        if new_pins:
            from trading.state import LIVE_STATE
            existing = list(LIVE_STATE.get("scan_watchlist") or [])
            merged   = list(dict.fromkeys(new_pins + existing))  # pins first, deduped
            LIVE_STATE["scan_watchlist"] = merged
            # Invalidate today's cached scan so the next full rescore includes the new tickers
            LIVE_STATE["scanner_ran_today"] = False
    except Exception:
        pass  # bot may not be running — non-fatal

    return payload


# ── API credentials ───────────────────────────────────────────────────────────

class CredentialsPayload(BaseModel):
    alpaca_api_key:     str
    alpaca_secret_key:  str
    tradier_api_key:    str = ""
    tradier_account_id: str = ""


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
    """
    from config import save_api_keys
    save_api_keys({
        "alpaca_api_key":     payload.alpaca_api_key.strip(),
        "alpaca_secret_key":  payload.alpaca_secret_key.strip(),
        "tradier_api_key":    payload.tradier_api_key.strip(),
        "tradier_account_id": payload.tradier_account_id.strip(),
    })
    return {"ok": True, "message": "API keys saved securely"}
