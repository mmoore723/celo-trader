"""
api/routes/settings.py — Settings read/write endpoints.
"""
from __future__ import annotations
from fastapi import APIRouter
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
        orb_enabled=bool(s.get("orb_enabled", True)),
        vwap_pullback_enabled=bool(s.get("vwap_pullback_enabled", True)),
        fvg_enabled=bool(s.get("fvg_enabled", True)),
        bos_mss_enabled=bool(s.get("bos_mss_enabled", True)),
    )


@router.post("", response_model=Settings)
def save_settings_endpoint(payload: Settings) -> Settings:
    from config import get_settings, save_settings
    current = get_settings()
    current.update(payload.model_dump())
    save_settings(current)
    return payload
