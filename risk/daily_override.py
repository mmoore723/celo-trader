"""Explicit, account-scoped daily loss allowance. Never changes saved settings."""
import json
import math
from functools import wraps
from datetime import datetime
from zoneinfo import ZoneInfo

from config import atomic_write_json
from risk.kill_lock import _lock_path


def serialized_loss_review(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from config.atomic_files import _lock_for
        with _lock_for(override_path()):
            return function(*args, **kwargs)
    return wrapped


def session_date():
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def override_path():
    path = _lock_path()
    return path.with_name("override_" + path.name)


def effective_limits(base, hard, soft):
    try:
        record = json.loads(override_path().read_text())
    except FileNotFoundError:
        return hard, soft
    if record["session"] != session_date():
        return hard, soft
    if record["scope"] != _lock_path().name:
        raise ValueError("Daily override account mismatch")
    limit = float(record["limit_usd"])
    if not math.isfinite(limit) or not 0 < limit <= base:
        raise ValueError("Invalid temporary daily loss limit")
    if abs(float(record["day_start"]) - base) > .01:
        raise ValueError("Daily override day-open mismatch")
    return limit / base, limit / base


def save_override(limit, base, session):
    if session != session_date():
        raise ValueError("Trading date changed. Reopen Resume trading.")
    atomic_write_json(override_path(), {
        "session": session, "scope": _lock_path().name,
        "limit_usd": limit, "day_start": base,
        "approved_at": datetime.now(ZoneInfo("UTC")).isoformat(),
    })
