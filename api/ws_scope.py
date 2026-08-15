"""Framework-free tenant scoping helpers for the live WebSocket feed."""
from __future__ import annotations


def entry_visible_to_user(entry: dict, user_id: str) -> bool:
    """Fail closed: unscoped and other-user records never reach the socket."""
    return bool(user_id) and entry.get("user_id") == user_id
