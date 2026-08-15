"""
trading/loop/lifecycle.py — Public lifecycle entry points for the trading
loop: run_trading_loop (singleton-guarded start), stop_loop, and
_sleep_until_next_day.

Split out of the old single trading/loop.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import json
import logging
import time
from datetime import timedelta

from trading.state import (
    _now_et,
    _get_stop_event,
    _get_lock,
    get_user_state,
    register_loop_thread,
    unregister_loop_thread,
)
from config import get_bot_state_path
from trading.loop.inner import _run_trading_loop_inner

logger = logging.getLogger("celo_trader.trading_logic")


def run_trading_loop(user_id: str, poll_interval: int = 10) -> None:
    """
    Singleton-guarded entry point.  One trading loop per user at a time.

    api/routes/bot.py::start_bot() spawns this via contextvars.copy_context()
    so the auth ContextVar (user identity) is already correct in this thread
    before this function even runs. BUT this function is also called from
    api/main.py's service-restart auto-resume path via a plain
    threading.Thread (no request in flight there to copy a context from) —
    so we explicitly (re)establish the ContextVar identity here ourselves,
    rather than assuming the caller already did it. This is what every
    downstream `get_user_state()` / `get_user_risk()` / `get_user_trade_log()`
    call (with no explicit user_id) resolves against, so getting this right
    is what makes the whole per-user state fix actually correct — without it,
    a bot resumed via the auto-start path would silently run against admin's
    state/risk/logger regardless of which user's loop this is.
    """
    try:
        from auth.context import set_current_user
        set_current_user(user_id, username=user_id, is_admin=False)
    except Exception as _ctx_err:
        logger.warning("run_trading_loop: could not set user context: %s", _ctx_err)

    from config import get_maintenance_state
    _maintenance = get_maintenance_state()
    if _maintenance.get("maintenance_mode", False) and not _maintenance.get("collection_only", False):
        logger.warning("run_trading_loop blocked by global maintenance for user %s", user_id)
        return

    _lock  = _get_lock(user_id)
    _stop  = _get_stop_event(user_id)
    if not _lock.acquire(blocking=False):
        logger.warning(
            "run_trading_loop called while loop for user %s is already running", user_id
        )
        from database import log_event
        log_event(
            "WARNING", "trading_logic",
            "⚠️ Start Bot pressed while a loop is already running — ignored. "
            "Press Stop first, wait a few seconds, then Start again."
        )
        return
    _thread = __import__("threading").current_thread()
    register_loop_thread(user_id, _thread)
    try:
        _stop.clear()
        _run_trading_loop_inner(user_id=user_id, poll_interval=poll_interval)
    finally:
        unregister_loop_thread(user_id, _thread)
        _lock.release()


def stop_loop(user_id: str) -> None:
    """Signal the loop for a given user to exit.

    FIX: this used to also unconditionally set the global LIVE_STATE alias
    (== admin's state) "running" = False and write the single shared root
    bot_state.json — so any user's Stop button also marked admin's dashboard
    stopped, and wrote to a file only admin's session actually read. Now
    scoped entirely to the calling user's own state and state file.
    """
    _get_stop_event(user_id).set()
    get_user_state(user_id)["running"] = False
    # Log to the database so the THINKING panel shows confirmation that the bot
    # actually received the stop signal (not just a network disconnect).
    try:
        from database import log_event
        log_event("INFO", "trading_logic", "🔴 Bot stopped.")
    except Exception:
        pass
    try:
        _state_path = get_bot_state_path(user_id)
        if _state_path.exists():
            _st = json.loads(_state_path.read_text())
            _st["running"] = False
            # auto_start_disabled = True tells the service-restart auto-start
            # logic NOT to resume the bot — the user explicitly pressed Stop.
            _st["auto_start_disabled"] = True
            # The loop writes this same dashboard snapshot periodically.  A
            # direct write can leave an empty/truncated JSON file if the two
            # writers overlap, which in turn loses the explicit-stop marker.
            # Replace is atomic on the server filesystem: readers see either
            # the old complete snapshot or the new complete snapshot.
            from config import atomic_write_json
            atomic_write_json(_state_path, _st)
    except Exception as _se:
        logger.warning("stop_loop: failed to update bot_state.json: %s", _se)


def _sleep_until_next_day() -> None:
    """Sleep until 9:31 ET on the next trading day."""
    now_et    = _now_et()
    next_open = now_et.replace(hour=9, minute=31, second=0, microsecond=0)
    next_open += timedelta(days=1)
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    secs = max(60, (next_open - _now_et()).total_seconds())
    logger.info("Sleeping %.1f hours until next market open", secs / 3600)
    time.sleep(secs)
