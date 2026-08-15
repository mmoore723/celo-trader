"""
trading/state/locks.py — per-user stop events, locks, and the
ContextVar-resolved "current user" helper.

Split out of the old single trading/state.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Each user gets their own stop event and lock so multiple users can run
concurrent bot instances without interfering. Legacy single-instance
symbols (_stop_event, _bot_loop_lock) refer to an isolated system tenant for
backward compatibility with import sites that cannot supply a user ID. They
must never inherit a real administrator's trading state.
"""

import threading

_USER_STOP_EVENTS: dict[str, threading.Event] = {}
_USER_LOCKS:       dict[str, threading.Lock]  = {}
_USER_THREADS:     dict[str, threading.Thread] = {}
_REGISTRY_LOCK = threading.RLock()


def _get_stop_event(user_id: str = "system") -> threading.Event:
    if user_id not in _USER_STOP_EVENTS:
        _USER_STOP_EVENTS[user_id] = threading.Event()
    return _USER_STOP_EVENTS[user_id]


def _get_lock(user_id: str = "system") -> threading.Lock:
    if user_id not in _USER_LOCKS:
        _USER_LOCKS[user_id] = threading.Lock()
    return _USER_LOCKS[user_id]


def register_loop_thread(user_id: str, thread: threading.Thread | None = None) -> None:
    """Record the process-local worker that owns ``user_id``'s loop."""
    with _REGISTRY_LOCK:
        _USER_THREADS[user_id] = thread or threading.current_thread()


def unregister_loop_thread(user_id: str, thread: threading.Thread | None = None) -> None:
    """Remove a worker only when it is the worker currently registered."""
    current = thread or threading.current_thread()
    with _REGISTRY_LOCK:
        if _USER_THREADS.get(user_id) is current:
            _USER_THREADS.pop(user_id, None)


def active_loop_threads() -> dict[str, threading.Thread]:
    """Return a stable snapshot for status checks and graceful shutdown."""
    with _REGISTRY_LOCK:
        return dict(_USER_THREADS)


def request_graceful_shutdown(timeout: float = 15.0) -> list[str]:
    """
    Ask every in-process trading loop to stop and wait briefly for completion.

    This deliberately does *not* set ``auto_start_disabled`` or rewrite the
    persisted ``running`` flag. A deploy/restart is different from a user's
    explicit Stop action: loops that were running should resume on next boot.
    Returns the user IDs whose threads remained alive after the deadline.
    """
    import time

    workers = active_loop_threads()
    for user_id in workers:
        _get_stop_event(user_id).set()

    deadline = time.monotonic() + max(0.0, timeout)
    for thread in workers.values():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if thread is not threading.current_thread():
            thread.join(timeout=remaining)

    return [user_id for user_id, thread in workers.items() if thread.is_alive()]


# Backward-compat aliases — deliberately isolated from every real user.
_stop_event    = _get_stop_event("system")
_bot_loop_lock = _get_lock("system")


def _default_user_id() -> str:
    """
    Resolve the calling user from the request-scoped ContextVar set by
    api/middleware/auth.py, falling back to the isolated ``system`` tenant
    when no authenticated request context exists.

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
        return "system"
