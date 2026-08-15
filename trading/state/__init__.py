"""
trading/state/__init__.py — Per-user mutable state for the entire trading
subsystem.

Every other trading/ module imports from here. USER_STATES[user_id] holds
each user's isolated state dict; get_user_state() (optionally called with
no argument) resolves the CURRENT user via the auth ContextVar snapshot the
calling thread was started with (see _default_user_id below), so any module
that does `_US = get_user_state()` gets that same live dict — mutations are
immediately visible everywhere else that resolves the same user_id. No
copies, no desync, and (unlike the old single-global-dict design) no
cross-user leakage either.

There is intentionally no process-global live-state alias. Every caller must
resolve a tenant explicitly or through the authenticated ContextVar.

Split (2026-08-01, file-size cleanup) out of the old single
trading/state.py into constants.py, locks.py, risk_log.py, and
user_state.py; no logic changed, only relocated. Every consumer in the repo
imports these names via `from trading.state import X` (confirmed via a
full-repo grep before this split — no file does a whole-module
`import trading.state as state`), so this __init__.py re-exports all of
them for exact backward compatibility. None of the underlying mutable dicts
(USER_STATES, _USER_STOP_EVENTS, _USER_LOCKS, _USER_RISK, _USER_TRADE_LOG)
are ever imported directly by external code — only through the accessor
functions below — so no special object-identity re-export tricks are
needed; each dict is simply defined once in its own submodule and the
accessor functions that close over it live in that same submodule.
"""

from trading.state.constants import (
    _BOT_ROOT,
    _ET_TZ,
    _now_et,
    _DATA_GAP_WARN_MINUTES,
    _DATA_GAP_PAUSE_MINUTES,
    logger,
)
from trading.state.locks import (
    _USER_STOP_EVENTS,
    _USER_LOCKS,
    _USER_THREADS,
    _get_stop_event,
    _get_lock,
    register_loop_thread,
    unregister_loop_thread,
    active_loop_threads,
    request_graceful_shutdown,
    _stop_event,
    _bot_loop_lock,
    _default_user_id,
)
from trading.state.risk_log import (
    _USER_RISK,
    get_user_risk,
    set_user_risk,
    _USER_TRADE_LOG,
    get_user_trade_log,
    set_user_trade_log,
)
from trading.state.user_state import (
    _make_initial_state,
    USER_STATES,
    get_user_state,
    _update_data_gap,
    reset_session_state,
)

__all__ = [
    "_BOT_ROOT",
    "_ET_TZ",
    "_now_et",
    "_DATA_GAP_WARN_MINUTES",
    "_DATA_GAP_PAUSE_MINUTES",
    "logger",
    "_USER_STOP_EVENTS",
    "_USER_LOCKS",
    "_USER_THREADS",
    "_get_stop_event",
    "_get_lock",
    "register_loop_thread",
    "unregister_loop_thread",
    "active_loop_threads",
    "request_graceful_shutdown",
    "_stop_event",
    "_bot_loop_lock",
    "_default_user_id",
    "_USER_RISK",
    "get_user_risk",
    "set_user_risk",
    "_USER_TRADE_LOG",
    "get_user_trade_log",
    "set_user_trade_log",
    "_make_initial_state",
    "USER_STATES",
    "get_user_state",
    "_update_data_gap",
    "reset_session_state",
]
