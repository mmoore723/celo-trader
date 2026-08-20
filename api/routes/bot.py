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
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from api.models import BotStatus, BotActionResponse

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _read_bot_state(user_id: str) -> dict[str, Any]:
    """
    Read only the explicitly identified user's state file. Requiring the
    caller to provide an identity prevents unauthenticated/background callers
    from silently inheriting another account's dashboard state.
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
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user context is missing")
    return str(user_id)


def _get_broker_alerts_safe() -> list[dict]:
    """Never let the alert banner itself take down /api/bot/status."""
    try:
        from broker_health import get_broker_alerts
        return get_broker_alerts()
    except Exception:
        return []


@router.get("/status", response_model=BotStatus)
def get_status(request: Request) -> BotStatus:
    from trading.state import _get_lock, get_user_state
    from config import get_api_keys, get_settings

    user_id  = _get_uid(request)
    state    = _read_bot_state(user_id)
    settings = get_settings()
    credentials = get_api_keys(user_id)
    broker_connected = all(
        str(credentials.get(key) or "").strip()
        for key in (
            "alpaca_api_key", "alpaca_secret_key",
            "tradier_api_key", "tradier_account_id",
        )
    )
    _state   = get_user_state(user_id)
    active_account = str(settings.get("active_broker_account_id") or "")
    state_account = str(state.get("broker_account_id") or _state.get("broker_account_id") or "")
    account_matches = not active_account or active_account == state_account

    lock = _get_lock(user_id)
    lock_acquired = lock.acquire(blocking=False)
    if lock_acquired:
        lock.release()
    actually_running = not lock_acquired

    from config import get_maintenance_state
    maintenance = get_maintenance_state()
    if broker_connected and account_matches:
        account_balance = float(
            state.get("account_balance")
            or _state.get("account_balance")
            or settings.get("last_known_balance", 0)
        )
        today_key = f"day_start_{datetime.now(ZoneInfo('America/New_York')).date().isoformat()}"
        day_start_balance = float(
            state.get("day_start_balance")
            or _state.get("day_start_balance")
            or settings.get(today_key)
            or account_balance
        )
        # Equity includes every open position's current mark, so this is live
        # session P&L rather than closed-trade-only realized P&L.
        session_pnl = round(account_balance - day_start_balance, 2)
    else:
        account_balance = 0.0
        day_start_balance = 0.0
        session_pnl = 0.0
    return BotStatus(
        running=actually_running and broker_connected,
        mode="paper" if settings.get("paper_trading", True) else "live",
        ticker=(state.get("current_ticker") or _state.get("current_ticker")) if broker_connected else None,
        broker_connected=broker_connected,
        account_balance=account_balance,
        day_start_balance=day_start_balance,
        session_pnl=session_pnl,
        options_buying_power=float(0 if not broker_connected else state.get("options_buying_power", 0.0)),
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
        # FIX 2026-07-31: same missing-field bug — see BotStatus.open_positions comment
        open_positions=dict(state.get("open_positions") or _state.get("open_positions") or {}),
        # 2026-07-31: see BotStatus.broker_alerts comment + broker_health.py
        broker_alerts=_get_broker_alerts_safe(),
        opportunity_window=dict(
            state.get("opportunity_scheduler") or _state.get("opportunity_scheduler") or {}
        ),
        maintenance_mode=bool(maintenance.get("maintenance_mode", False)),
        maintenance_message=str(maintenance.get("maintenance_message", "")),
        collection_only=bool(maintenance.get("collection_only", False)),
    )


@router.post("/start", response_model=BotActionResponse)
def start_bot(request: Request) -> BotActionResponse:
    from trading.loop import run_trading_loop
    from trading.state import _get_lock, _get_stop_event
    from config import get_api_keys, get_settings, get_maintenance_state

    user_id  = _get_uid(request)
    lock     = _get_lock(user_id)
    # Mode is controlled exclusively via Settings (paper_trading flag).
    # Never overwrite it here — read whatever the user last saved.
    settings = get_settings()
    mode     = "paper" if settings.get("paper_trading", True) else "live"

    credentials = get_api_keys(user_id)
    missing_credentials = [
        label
        for key, label in (
            ("alpaca_api_key", "Alpaca API key"),
            ("alpaca_secret_key", "Alpaca secret key"),
            ("tradier_api_key", "Tradier API key"),
            ("tradier_account_id", "Tradier account ID"),
        )
        if not str(credentials.get(key) or "").strip()
    ]
    if missing_credentials:
        return BotActionResponse(
            ok=False,
            message=(
                "Broker connection required. Add "
                + ", ".join(missing_credentials)
                + " in Settings before starting the bot."
            ),
        )

    # A full maintenance halt blocks loops. Collection-only maintenance may
    # run the scanner/recorder, while the entry path independently guarantees
    # that no order or exit can be submitted.
    maintenance = get_maintenance_state()
    if maintenance.get("maintenance_mode", False) and not maintenance.get("collection_only", False):
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
    if maintenance.get("maintenance_mode", False):
        return BotActionResponse(ok=True, message="Data collection started; trading remains globally halted")
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
