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
    from trading.state import _bot_loop_lock
    from config import get_settings, STARTING_CAPITAL

    state = _read_bot_state()
    settings = get_settings()

    # Lock is held only while the bot loop is actually running.
    # This is more reliable than the stale bot_state.json "running" flag.
    lock_acquired = _bot_loop_lock.acquire(blocking=False)
    if lock_acquired:
        _bot_loop_lock.release()
    actually_running = not lock_acquired  # True = lock is held = bot is running

    return BotStatus(
        running=actually_running,
        mode=str(state.get("mode", LIVE_STATE.get("mode", "stopped"))),
        ticker=state.get("current_ticker") or state.get("ticker") or LIVE_STATE.get("current_ticker") or LIVE_STATE.get("ticker"),
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
        is_paper=bool(settings.get("paper_trading", True)),
        last_eval_strike=state.get("last_eval_strike") or LIVE_STATE.get("last_eval_strike"),
        last_eval_expiry=state.get("last_eval_expiry") or LIVE_STATE.get("last_eval_expiry"),
        last_eval_contract_symbol=state.get("last_eval_contract_symbol") or LIVE_STATE.get("last_eval_contract_symbol"),
        last_eval_eff_entry=state.get("last_eval_eff_entry") or LIVE_STATE.get("last_eval_eff_entry"),
        last_eval_contracts=state.get("last_eval_contracts") if state.get("last_eval_contracts") is not None else LIVE_STATE.get("last_eval_contracts"),
        last_eval_opt_type=state.get("last_eval_opt_type") or LIVE_STATE.get("last_eval_opt_type"),
        last_eval_ticker=state.get("last_eval_ticker") or LIVE_STATE.get("last_eval_ticker"),
    )


@router.post("/start", response_model=BotActionResponse)
def start_bot(mode: str = "paper") -> BotActionResponse:
    from trading_logic import run_trading_loop, LIVE_STATE
    from trading.state import _bot_loop_lock

    # Prefer the live lock over stale bot_state.json "running" flag
    lock_held = not _bot_loop_lock.acquire(blocking=False)
    if lock_held:
        return BotActionResponse(ok=False, message="Bot is already running")
    # Released immediately — we only peeked; run_trading_loop acquires it properly
    _bot_loop_lock.release()

    # Apply mode to settings BEFORE the loop starts reading them
    from config import save_settings
    save_settings({"paper_trading": mode != "live"})

    # run_trading_loop(poll_interval: int) — do NOT pass mode as a positional arg
    thread = threading.Thread(
        target=run_trading_loop, daemon=True, name="celo-bot"
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
