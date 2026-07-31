"""
broker_health.py — Rolling broker-error tracker for the dashboard alert banner.

Added 2026-07-31: Tradier auth broke (a masked credential got saved over the
real key — see api/routes/settings.py's credentials-save fix, same incident)
and ran silently for at least 7 minutes, 268 failed calls across every
ticker, with zero visible indication anywhere except individual
"no_option_data" signal-journal rows that look like normal signal noise,
one ticker at a time. Alpaca already has a circuit breaker (see broker.py)
but nothing surfaces ITS state to the dashboard either, and Tradier had no
tracking of any kind. This is deliberately simpler than a circuit breaker —
it doesn't block calls, it just counts recent failures per broker and
exposes an alert once the rate crosses a threshold, so a human sees it
immediately instead of finding out from a chart review days later.
"""
from __future__ import annotations

import time
from collections import deque

_WINDOW_SEC      = 180   # rolling window: last 3 minutes
_ALERT_THRESHOLD = 5     # >= this many failures in the window triggers an alert

# {"tradier": deque[(ts, error_str)], "alpaca": deque[(ts, error_str)]}
_failures: dict[str, deque] = {"tradier": deque(), "alpaca": deque()}


def _prune(dq: deque, now: float) -> None:
    while dq and now - dq[0][0] > _WINDOW_SEC:
        dq.popleft()


def record_broker_error(broker: str, error: str) -> None:
    """
    Call from a broker client's failure path. Append-only deque use is
    thread-safe enough for this — worst case is a rare dropped/duplicated
    read, never a crash, and this only feeds a dashboard banner, not trade
    logic or risk decisions.
    """
    now = time.time()
    dq = _failures.setdefault(broker, deque())
    dq.append((now, str(error)[:200]))   # cap length — this is a display string, not a log
    _prune(dq, now)


def record_broker_success(broker: str) -> None:
    """Clear the window on a successful call — a single good call means the
    outage (if any) is over, don't keep alerting on stale failures."""
    _failures[broker] = deque()


def get_broker_alerts() -> list[dict]:
    """Return one alert dict per broker currently over threshold."""
    now = time.time()
    alerts = []
    for broker, dq in _failures.items():
        _prune(dq, now)
        if len(dq) >= _ALERT_THRESHOLD:
            first_ts, _ = dq[0]
            _, last_err = dq[-1]
            alerts.append({
                "broker":      broker,
                "error_count": len(dq),
                "since":       first_ts,
                "last_error":  last_err,
            })
    return alerts
