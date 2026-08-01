"""
trading/state/locks.py — per-user stop events, locks, and the
ContextVar-resolved "current user" helper.

Split out of the old single trading/state.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Each user gets their own stop event and lock so multiple users can run
concurrent bot instances without interfering. Legacy single-instance
symbols (_stop_event, _bot_loop_lock) still refer to the "admin" user's
state for backward-compat with existing import sites.
"""

import threading

_USER_STOP_EVENTS: dict[str, threading.Event] = {}
_USER_LOCKS:       dict[str, threading.Lock]  = {}


def _get_stop_event(user_id: str = "admin") -> threading.Event:
    if user_id not in _USER_STOP_EVENTS:
        _USER_STOP_EVENTS[user_id] = threading.Event()
    return _USER_STOP_EVENTS[user_id]


def _get_lock(user_id: str = "admin") -> threading.Lock:
    if user_id not in _USER_LOCKS:
        _USER_LOCKS[user_id] = threading.Lock()
    return _USER_LOCKS[user_id]


# Backward-compat aliases — point to admin user's primitives
_stop_event    = _get_stop_event("admin")
_bot_loop_lock = _get_lock("admin")


def _default_user_id() -> str:
    """
    Resolve the calling user from the request-scoped ContextVar set by
    api/middleware/auth.py, falling back to "admin" for background-thread
    or single-user code paths where no request context exists.

    Background trading-loop threads are started via contextvars.copy_context()
    (see api/routes/bot.py::start_bot), which snapshots this ContextVar at
    thread-start time — so a call made from inside a user's own loop thread
    resolves to *that* user for the thread's entire lifetime, not whichever
    request happens to be in flight at the moment of the call.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "admin"
