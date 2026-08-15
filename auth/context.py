"""
auth/context.py — ContextVar for the currently authenticated user.

Used by:
  - api/middleware/auth.py  → sets user_id after JWT decode
  - config.py               → reads user_id to resolve per-user paths
  - api/routes/bot.py       → copies context into bot thread via copy_context()

Why ContextVar:
  FastAPI runs each request as an async coroutine with its own context.
  Setting a ContextVar in middleware propagates it to all downstream
  awaitable calls in that same coroutine without changing any function
  signatures. copy_context() snapshots it into background threads.
"""
from __future__ import annotations
from contextvars import ContextVar

# Code running without an authenticated request or an explicitly-scoped bot
# worker is system work.  It must never inherit the first administrator's
# files or privileges merely because no ContextVar was set.
_user_id_var:   ContextVar[str]  = ContextVar("celo_user_id",   default="system")
_is_admin_var:  ContextVar[bool] = ContextVar("celo_is_admin",  default=False)
_username_var:  ContextVar[str]  = ContextVar("celo_username",  default="system")


def set_current_user(user_id: str, username: str, is_admin: bool) -> None:
    """Call once per request (in auth middleware) to set request-scoped user."""
    _user_id_var.set(user_id)
    _username_var.set(username)
    _is_admin_var.set(is_admin)


def get_current_user_id() -> str:
    return _user_id_var.get()


def get_current_username() -> str:
    return _username_var.get()


def get_current_is_admin() -> bool:
    return _is_admin_var.get()
