"""
api/routes/bot.py — Bot control and live state endpoints.
"""
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from api.models import BotStatus, BotActionResponse

router = APIRouter(prefix="/api/bot", tags=["bot"])

_BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "bot_state.json"


def _read_bot_state() -> dict[str, Any]:
    try:
        if _BOT_STATE_PATH.exists():
            return json.loads(_BOT_STATE_PATH.read_text())
    except Exception:
        pass
    return {}


@router.get("/status", response_model=BotStatus)
def get_status() -> BotStatus:
    from trading_logic import LIVE_STATE
    from config import get_settings, STARTING_CAPITAL

    state = _read_bot_state()
    settings = get_settings()

    return BotStatus(
        running=bool(state.get("running", LIVE_STATE.get("running", False))),
        mode=str(state.get("mode", LIVE_STATE.get("mode", "stopped"))),
        ticker=state.get("ticker") or LIVE_STATE.get("ticker"),
        account_balance=float(
            state.get("account_balance")
            or LIVE_STATE.get("account_balance")
            or settings.get("last_known_balance", STARTING_CAPITAL)
        ),
        session_pnl=float(state.get("session_pnl", LIVE_STATE.get("session_pnl", 0.0))),
        options_buying_power=float(state.get("options_buying_power", 0.0)),
        last_update=state.get("last_update"),
        network_ok=bool(state.get("network_ok", True)),
        last_strategy_id=state.get("last_strategy_id") or LIVE_STATE.get("last_strategy_id"),
        current_stop_pct=state.get("current_stop_pct"),
        last_signal=state.get("last_signal"),
        ghost_position_detected=bool(state.get("ghost_position_detected", False)),
    )


@router.post("/start", response_model=BotActionResponse)
def start_bot(mode: str = "paper") -> BotActionResponse:
    from trading_logic import run_trading_loop, LIVE_STATE
    if LIVE_STATE.get("running"):
        return BotActionResponse(ok=False, message="Bot is already running")
    thread = threading.Thread(
        target=run_trading_loop, args=(mode,), daemon=True, name="celo-bot"
    )
    thread.start()
    return BotActionResponse(ok=True, message=f"Bot started in {mode} mode")


@router.post("/stop", response_model=BotActionResponse)
def stop_bot() -> BotActionResponse:
    from trading_logic import stop_loop
    stop_loop()
    return BotActionResponse(ok=True, message="Bot stop signal sent")


@router.post("/panic", response_model=BotActionResponse)
def panic_close() -> BotActionResponse:
    from trading_logic import panic_close_all
    panic_close_all()
    return BotActionResponse(ok=True, message="Panic close triggered")


@router.post("/reset", response_model=BotActionResponse)
def reset_session() -> BotActionResponse:
    from trading_logic import reset_session_state
    reset_session_state()
    return BotActionResponse(ok=True, message="Session state reset")


@router.post("/close/{trade_id}", response_model=BotActionResponse)
def close_trade(trade_id: int) -> BotActionResponse:
    from trading_logic import close_trade_by_id
    try:
        close_trade_by_id(trade_id)
        return BotActionResponse(ok=True, message=f"Close signal sent for trade {trade_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
