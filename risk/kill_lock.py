"""Account-scoped durable daily-loss halt and outstanding flatten request."""
import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from config import get_settings, get_user_data_dir, atomic_write_json, KILL_LOCK_HOURS

logger = logging.getLogger("celo_trader.risk")
# Ownerless legacy locks still block entries; they cannot authorize account exits.
_KILL_LOCK_PATH = Path(__file__).resolve().parent.parent / "kill_lock.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _lock_path() -> Path:
    settings = get_settings()
    identity = json.dumps([settings.get("broker_provider", "alpaca"),
                           bool(settings.get("paper_trading", True)),
                           settings.get("active_broker_account_id") or "unattributed"])
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return get_user_data_dir(create=False) / f"daily_loss_{digest}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    datetime.fromisoformat(data["locked_until_utc"])
    if (path != _KILL_LOCK_PATH and "flatten_pending" not in data) or not isinstance(data.get("flatten_pending", False), bool):
        raise ValueError("Invalid flatten state")
    return data


def set_kill_lock(hours: float | None = None, *, until: datetime | None = None,
                  reason: str = "daily_loss_hard_cap") -> datetime:
    """Persist BEFORE broker side effects; storage errors propagate."""
    path = _lock_path()
    now = _utcnow()
    existing = _read(path)
    duration = hours if hours is not None else float(get_settings().get("kill_lock_hours", KILL_LOCK_HOURS))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Positive kill-lock duration required")
    expires = until or now + timedelta(hours=duration)
    if expires.tzinfo is not None:
        expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
    if existing and (existing.get("flatten_pending") or now < datetime.fromisoformat(existing["locked_until_utc"])):
        return datetime.fromisoformat(existing["locked_until_utc"])
    atomic_write_json(path, {"locked_until_utc": expires.isoformat(), "set_at_utc": now.isoformat(),
                             "reason": reason, "flatten_pending": True})
    return expires


def flatten_pending() -> bool:
    data = _read(_lock_path())
    return bool(data and data.get("flatten_pending"))


def confirm_flattened() -> None:
    """Only after journal AND broker confirm flat with no pending orders."""
    path = _lock_path()
    data = _read(path)
    if data:
        data.update(flatten_pending=False, flat_confirmed_at_utc=_utcnow().isoformat())
        atomic_write_json(path, data)


def check_kill_lock() -> tuple[bool, str | None]:
    try:
        for path in (_lock_path(), _KILL_LOCK_PATH):
            data = _read(path)
            if not data:
                continue
            if data.get("flatten_pending"):
                return True, "Daily loss halt — broker close confirmation pending"
            expires = datetime.fromisoformat(data["locked_until_utc"])
            if _utcnow() < expires:
                return True, f"Kill-locked until {expires:%Y-%m-%d %H:%M} UTC"
    except Exception:
        logger.exception("Daily-loss state unavailable; blocking new entries")
        return True, "Daily loss state unavailable — new entries blocked"
    return False, None


def clear_kill_lock() -> None:
    path = _lock_path()
    data = _read(path)
    if data and data.get("flatten_pending"):
        raise RuntimeError("Cannot unlock while emergency closes are unconfirmed")
    path.unlink(missing_ok=True)
