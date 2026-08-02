"""Causal, paper-only scheduler for lower-confidence opportunity signals.

Main-tier signals are deliberately never delayed.  An opportunity signal is
collected for a fixed window, ranked against later *observed* candidates, and
only used if the winning setup still confirms when its window closes.  This is
not a look-ahead: live trading waits in real time, and the backtester advances
one historical bar at a time through the same state machine.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Literal, NamedTuple


WINDOW_MINUTES = 15
MAIN_TIER = "main"
OPPORTUNITY_TIER = "opportunity"


class Selection(NamedTuple):
    action: Literal["select", "waiting", "expired", "empty"]
    signal: Any | None
    event: str | None
    candidate: dict[str, Any] | None


def _tier(signal: Any) -> str:
    return getattr(signal, "tier", MAIN_TIER)


def _snapshot(signal: Any, ticker: str, now: datetime) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "strategy_id": str(getattr(signal, "strategy_id", "UNKNOWN")),
        "direction": str(getattr(signal, "direction", "unknown")),
        "confidence": float(getattr(signal, "confidence", 0.0)),
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=WINDOW_MINUTES)).isoformat(),
    }


def _parse(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def clear(state: dict[str, Any]) -> None:
    state["opportunity_scheduler"] = {}


def due_ticker(state: dict[str, Any], now: datetime) -> str | None:
    """Return the candidate ticker once its window is due for confirmation."""
    candidate = state.get("opportunity_scheduler") or {}
    expires_at = _parse(candidate.get("expires_at"))
    ticker = candidate.get("ticker")
    return str(ticker) if ticker and expires_at is not None and now >= expires_at else None


def select(
    state: dict[str, Any],
    ticker: str,
    signals: Iterable[Any],
    now: datetime,
) -> Selection:
    """Choose an immediate main setup or manage one opportunity collection window.

    The caller invokes this after all normal router quality gates.  It returns
    `waiting` while the best lower-confidence candidate is being collected,
    `select` for a main signal or a confirmed scheduled opportunity signal, and
    `expired` when the candidate no longer confirms at its decision point.
    """
    candidates = list(signals)
    main = [signal for signal in candidates if _tier(signal) != OPPORTUNITY_TIER]
    window = state.get("opportunity_scheduler") or {}

    # Main evidence always wins immediately; an unfinished research window is
    # explicitly recorded as preempted rather than silently surviving.
    if main:
        event = "main_preempted" if window else None
        prior = dict(window) if window else None
        if window:
            clear(state)
        return Selection("select", main[0], event, prior)

    opportunity = [signal for signal in candidates if _tier(signal) == OPPORTUNITY_TIER]
    expires_at = _parse(window.get("expires_at")) if window else None

    if not window:
        if not opportunity:
            return Selection("empty", None, None, None)
        best = max(opportunity, key=lambda signal: float(getattr(signal, "confidence", 0.0)))
        snap = _snapshot(best, ticker, now)
        state["opportunity_scheduler"] = snap
        return Selection("waiting", best, "started", snap)

    # During the window, retain only a strictly stronger observed candidate.
    if expires_at is not None and now < expires_at:
        if opportunity:
            best = max(opportunity, key=lambda signal: float(getattr(signal, "confidence", 0.0)))
            if float(getattr(best, "confidence", 0.0)) > float(window.get("confidence", 0.0)):
                snap = _snapshot(best, ticker, now)
                # The collection deadline belongs to the first candidate; a
                # stronger later signal replaces rank, not the clock.
                snap["started_at"] = window.get("started_at", snap["started_at"])
                snap["expires_at"] = window.get("expires_at", snap["expires_at"])
                state["opportunity_scheduler"] = snap
                return Selection("waiting", best, "replaced", snap)
        return Selection("waiting", None, None, dict(window))

    # The scheduled ticker is scanned specifically at expiry.  Require the
    # winner's strategy and direction to still be present; entering a stale
    # 15-minute-old setup would be future-looking in a replay and unsafe live.
    if ticker == window.get("ticker"):
        matching = [
            signal for signal in opportunity
            if getattr(signal, "strategy_id", None) == window.get("strategy_id")
            and getattr(signal, "direction", None) == window.get("direction")
        ]
        clear(state)
        if matching:
            return Selection("select", max(matching, key=lambda signal: float(getattr(signal, "confidence", 0.0))), "confirmed", dict(window))
        return Selection("expired", None, "confirmation_lost", dict(window))

    # Caller should use due_ticker() to avoid this branch live.  Keeping the
    # candidate intact here makes the helper safe if scanner selection changes.
    return Selection("waiting", None, None, dict(window))
