"""In-memory deduplication for AI reviews of persistent scanner setups."""

from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any


EPISODE_QUIET_MINUTES = 15


@dataclass(frozen=True)
class ObservationScheduled:
    """Internal marker; it is never persisted as an AI verdict."""

    action: str = "observe"
    size_multiplier: float = 1.0
    rationale: str = ""
    error: None = None


def episode_key(ticker: object, strategy_id: object, direction: object) -> str:
    return "|".join(str(value or "").strip().upper() for value in (ticker, strategy_id, direction))


def cached_review(
    cache: dict[str, dict[str, Any]], *, key: str, observed_at: datetime,
    quiet_minutes: int = EPISODE_QUIET_MINUTES,
) -> Any | None:
    """Return the first clean review while this setup episode persists.

    ``last_seen`` advances on every repeated detection.  A fresh episode starts
    only after the strategy/direction combination was absent for the quiet
    period, matching the scorecard's independence rule.
    """
    existing = cache.get(key)
    if not isinstance(existing, dict):
        return None
    last_seen = existing.get("last_seen")
    if not isinstance(last_seen, datetime) or observed_at - last_seen > timedelta(minutes=quiet_minutes):
        cache.pop(key, None)
        return None
    existing["last_seen"] = observed_at
    return existing.get("result")


def remember_review(
    cache: dict[str, dict[str, Any]], *, key: str, observed_at: datetime, result: Any,
) -> None:
    """Remember only clean model responses; failures remain eligible to retry."""
    if result is None or getattr(result, "error", None):
        return
    cache[key] = {"first_seen": observed_at, "last_seen": observed_at, "result": result}


def complete_observation(
    cache: dict[str, dict[str, Any]], *, key: str, marker: Any, result: Any,
) -> bool:
    """Atomically replace this worker's marker, or remove it after failure.

    A late worker cannot overwrite a newer episode because replacement only
    occurs when the cached object is the exact marker that worker created.
    """
    current = cache.get(key)
    if not isinstance(current, dict) or current.get("result") is not marker:
        return False
    if result is None or getattr(result, "error", None):
        cache.pop(key, None)
    else:
        current["result"] = result
    return True
