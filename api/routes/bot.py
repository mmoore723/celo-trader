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
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models import BotStatus, BotActionResponse

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _read_bot_state(user_id: str = "admin") -> dict[str, Any]:
    """
    FIX: this used to always read the single shared root-level bot_state.json
    regardless of which user was asking — a non-admin user's dashboard showed
    admin's balance/positions/status. Now reads that user's own state file
    (see config.get_bot_state_path, which migrates admin's legacy root file
    in automatically the first time it's called for "admin").
    """
    try:
        from config import get_bot_state_path
        _path = get_bot_state_path(user_id)
        if _path.exists():
            return json.loads(_path.read_text())
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
    state    = _read_bot_state(user_id)
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
        day_start_balance=float(
            state.get("day_start_balance")
            or _state.get("day_start_balance")
            or state.get("account_balance")
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
        # FIX 2026-07-28: was never passed through — see BotStatus.eval_log comment
        eval_log=list(state.get("eval_log") or _state.get("eval_log") or []),
        maintenance_mode=bool(settings.get("maintenance_mode", False)),
        maintenance_message=str(settings.get("maintenance_message", "")),
    )


@router.post("/start", response_model=BotActionResponse)
def start_bot(request: Request) -> BotActionResponse:
    from trading.loop import run_trading_loop
    from trading.state import _get_lock, _get_stop_event
    from config import get_settings

    user_id  = _get_uid(request)
    lock     = _get_lock(user_id)
    # Mode is controlled exclusively via Settings (paper_trading flag).
    # Never overwrite it here — read whatever the user last saved.
    settings = get_settings()
    mode     = "paper" if settings.get("paper_trading", True) else "live"

    # Block start during maintenance — admin must clear it first
    if settings.get("maintenance_mode", False):
        return BotActionResponse(
            ok=False,
            message="🔧 System is in maintenance mode. Clear it from the Admin page before starting the bot."
        )

    lock_held = not lock.acquire(blocking=False)
    if lock_held:
        return BotActionResponse(ok=False, message="Bot is already running")
    lock.release()

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
def stop_bot(request: Request) -> BotActionResponse:
    from trading.loop import stop_loop
    stop_loop(_get_uid(request))
    return BotActionResponse(ok=True, message="Bot stop signal sent")


@router.post("/panic", response_model=BotActionResponse)
def panic_close(request: Request) -> BotActionResponse:
    from trading.controls import panic_close_all
    panic_close_all(_get_uid(request))
    return BotActionResponse(ok=True, message="Panic close triggered")


@router.post("/reset", response_model=BotActionResponse)
def reset_session(request: Request) -> BotActionResponse:
    from trading.state import reset_session_state
    reset_session_state(_get_uid(request))
    return BotActionResponse(ok=True, message="Session state reset")


@router.get("/trade-events/{trade_id}")
def get_trade_events(trade_id: int) -> list[dict]:
    """
    Return all system_events tagged to the given trade since its entry time.
    Filters by [TICKER] pattern in the message so only that ticker's events show.
    """
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ticker, entry_time FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")
        ticker   = row["ticker"]
        entry_ts = row["entry_time"]
        events   = conn.execute(
            """SELECT ts, level, component, message
               FROM system_events
               WHERE ts >= ?
               AND message LIKE '%[' || ? || ']%'
               ORDER BY ts ASC
               LIMIT 500""",
            (entry_ts, ticker),
        ).fetchall()
    return [dict(e) for e in events]


@router.get("/annotations/{ticker}")
def get_chart_annotations(ticker: str, request: Request) -> list[dict]:
    """
    Return all chart annotations accumulated by the bot for the given ticker
    this session.  Used by the frontend to overlay bot-detected patterns
    (FVG zones, BOS levels, signal/veto markers) on the price chart.
    Annotations live in this user's state["chart_annotations"][TICKER].

    FIX: previously always read the global LIVE_STATE alias (admin's
    annotations) regardless of who was asking.
    """
    from trading.state import get_user_state
    _state = get_user_state(_get_uid(request))
    anns = _state.get("chart_annotations", {}).get(ticker.upper(), [])
    return list(anns)


@router.post("/close/{trade_id}", response_model=BotActionResponse)
def close_trade(trade_id: int, request: Request) -> BotActionResponse:
    from trading.controls import close_trade_by_id
    try:
        close_trade_by_id(trade_id, _get_uid(request))
        return BotActionResponse(ok=True, message=f"Close signal sent for trade {trade_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
