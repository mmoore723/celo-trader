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
        # All strategy flags use the strategy_*_enabled keys that entry.py reads
        orb_enabled=bool(s.get("strategy_orb_enabled", True)),
        vwap_pullback_enabled=bool(s.get("strategy_vwap_enabled", True)),
        fvg_enabled=bool(s.get("strategy_fvg_enabled", True)),
        bos_mss_enabled=bool(s.get("strategy_bos_enabled", True)),
        chan_break_enabled=bool(s.get("strategy_chan_enabled", True)),
        mid_brk_enabled=bool(s.get("strategy_mid_enabled", True)),
        trend_cont_enabled=bool(s.get("strategy_tcont_enabled", True)),
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
    return payload
