"""
api/routes/bot.py — Bot control and live state endpoints.

Multi-user: each user gets their own bot thread, stop event, and lock.
copy_context() captures the ContextVar (user_id) at request time and runs
the bot loop in it — all get_settings/get_db_path/get_api_keys calls resolve
to the right user throughout the entire loop without changing any signatures.
"""
from __future__ import annotations
import json
import threading
import contextvars
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

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


def _get_uid(request: Request) -> str:
    return getattr(request.state, "user_id", "admin")


@router.get("/status", response_model=BotStatus)
def get_status(request: Request) -> BotStatus:
    from trading.state import _get_lock, get_user_state
    from config import get_settings, STARTING_CAPITAL

    user_id  = _get_uid(request)
    state    = _read_bot_state()
    settings = get_settings()
    _state   = get_user_state(user_id)

    lock = _get_lock(user_id)
    lock_acquired = lock.acquire(blocking=False)
    if lock_acquired:
        lock.release()
    actually_running = not lock_acquired

    return BotStatus(
        running=actually_running,
        mode=str(state.get("mode", _state.get("mode", "stopped"))),
        ticker=state.get("current_ticker") or _state.get("current_ticker"),
        account_balance=float(
            state.get("account_balance")
            or _state.get("account_balance")
            or settings.get("last_known_balance", STARTING_CAPITAL)
        ),
        session_pnl=float(state.get("session_pnl", _state.get("session_pnl", 0.0))),
        options_buying_power=float(state.get("options_buying_power", 0.0)),
        last_update=state.get("last_update"),
        network_ok=bool(state.get("network_ok", True)),
        last_strategy_id=state.get("last_strategy_id") or _state.get("last_strategy_id"),
        current_stop_pct=state.get("current_stop_pct"),
        last_signal=state.get("last_signal"),
        ghost_position_detected=bool(state.get("ghost_position_detected", False)),
        is_paper=bool(settings.get("paper_trading", True)),
        last_eval_strike=state.get("last_eval_strike") or _state.get("last_eval_strike"),
        last_eval_expiry=state.get("last_eval_expiry") or _state.get("last_eval_expiry"),
        last_eval_contract_symbol=state.get("last_eval_contract_symbol") or _state.get("last_eval_contract_symbol"),
        last_eval_eff_entry=state.get("last_eval_eff_entry") or _state.get("last_eval_eff_entry"),
        last_eval_contracts=state.get("last_eval_contracts") if state.get("last_eval_contracts") is not None else _state.get("last_eval_contracts"),
        last_eval_opt_type=state.get("last_eval_opt_type") or _state.get("last_eval_opt_type"),
        last_eval_ticker=state.get("last_eval_ticker") or _state.get("last_eval_ticker"),
    )


@router.post("/start", response_model=BotActionResponse)
def start_bot(request: Request, mode: str = "paper") -> BotActionResponse:
    from trading.loop import run_trading_loop
    from trading.state import _get_lock, _get_stop_event
    from config import save_settings

    user_id = _get_uid(request)
    lock    = _get_lock(user_id)

    lock_held = not lock.acquire(blocking=False)
    if lock_held:
        return BotActionResponse(ok=False, message="Bot is already running")
    lock.release()

    save_settings({"paper_trading": mode != "live"})
    _get_stop_event(user_id).clear()

    # copy_context() captures ContextVars (incl. user_id) so all per-user
    # helpers (get_settings, get_db_path, get_api_keys, broker) resolve
    # correctly throughout the entire bot loop thread lifetime.
    ctx = contextvars.copy_context()
    thread = threading.Thread(
        target=ctx.run,
        args=(run_trading_loop,),
        kwargs={"user_id": user_id},
        daemon=True,
        name=f"celo-bot-{user_id}",
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
