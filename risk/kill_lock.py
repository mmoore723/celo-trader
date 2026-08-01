"""
risk/kill_lock.py — 24-hour trading freeze after the daily hard-loss cap.

Split out of risk.py (2026-08-01, file-size cleanup) — pure functions, no
RiskManager state, so this has zero coupling to the rest of the package.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import get_settings, KILL_LOCK_HOURS

logger = logging.getLogger("celo_trader.risk")

_KILL_LOCK_PATH = Path(__file__).resolve().parent.parent / "kill_lock.json"


def set_kill_lock(hours: Optional[int] = None) -> datetime:
    """
    Write a kill-lock file that blocks all trading for `hours` hours.
    Returns the datetime when the lock expires.
    """
    lock_hours = hours or int(get_settings().get("kill_lock_hours", KILL_LOCK_HOURS))
    expires_at = datetime.utcnow() + timedelta(hours=lock_hours)
    try:
        _KILL_LOCK_PATH.write_text(json.dumps({
            "locked_until_utc": expires_at.isoformat(),
            "set_at_utc":       datetime.utcnow().isoformat(),
            "reason":           "daily_loss_hard_cap",
        }))
        logger.warning(
            "kill_lock_set",
            extra={
                "event":       "kill_lock_set",
                "expires_utc": expires_at.isoformat(),
                "lock_hours":  lock_hours,
            },
        )
    except Exception as ex:
        logger.error("Failed to write kill lock: %s", ex)
    return expires_at


def check_kill_lock() -> tuple[bool, Optional[str]]:
    """
    Returns (locked: bool, reason: str | None).
    Locked = True means trading must be blocked until the timestamp expires.
    """
    if not _KILL_LOCK_PATH.exists():
        return False, None
    try:
        data       = json.loads(_KILL_LOCK_PATH.read_text())
        expires_at = datetime.fromisoformat(data["locked_until_utc"])
        if datetime.utcnow() < expires_at:
            remaining = expires_at - datetime.utcnow()
            hours_left = remaining.total_seconds() / 3600
            return True, f"Kill-locked: {hours_left:.1f}h remaining (expires {expires_at.strftime('%Y-%m-%d %H:%M')} UTC)"
        else:
            # Lock expired — clean up
            _KILL_LOCK_PATH.unlink(missing_ok=True)
    except Exception as ex:
        logger.warning("kill lock read error: %s", ex)
    return False, None


def clear_kill_lock() -> None:
    """Manually clear the kill lock (for admin / dashboard use)."""
    try:
        _KILL_LOCK_PATH.unlink(missing_ok=True)
        logger.info("kill_lock_cleared", extra={"event": "kill_lock_cleared"})
    except Exception:
        pass
