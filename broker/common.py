"""
broker/common.py — Shared helpers used by both AlpacaClient and TradierClient:
retry/circuit-breaker infrastructure, audit-log debouncing, and the two small
free functions (is_phantom_position_rejection, _extract_partial_fill) that
interpret broker responses without needing any client instance.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import time
import logging
from typing import Optional

import requests

from database import log_event

logger = logging.getLogger("celo_trader.broker")

# ── Local market-hours fallback ──────────────────────────────────────────────
def _local_market_is_open() -> bool:
    """
    Pure local-time check — no network call.
    Used as a fallback when the Alpaca circuit breaker is active so
    is_market_open() doesn't incorrectly return False during regular hours.
    Returns True Monday–Friday 9:30–16:00 ET.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        if now.weekday() >= 5:
            return False
        hm = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= hm < 16 * 60
    except Exception:
        return False


# ── Audit-log debounce ────────────────────────────────────────────────────────
# Prevents the same API error flooding the system_events table on every
# auto-refresh cycle.  Key = (event_type, module, url_base); value = epoch when
_audit_debounce: dict = {}
_AUDIT_DEBOUNCE_S = 300   # 5 minutes between identical DB error entries

def _debounced_log(level: str, module: str, message: str) -> None:
    """Write to system_events only if the same message wasn't written recently."""
    key = (level, module, message[:80])   # truncate key for dict efficiency
    now = time.time()
    if now - _audit_debounce.get(key, 0) >= _AUDIT_DEBOUNCE_S:
        _audit_debounce[key] = now
        log_event(level, module, message)

# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, delay: float = 0.5):
    """
    Linear back-off retry: 1.5s, 3s, 4.5s.

    Errors that should NOT be retried (raise immediately on attempt 1):
      • HTTP 4xx  — client/permission errors; won't change with retries
      • ConnectionError / NameResolutionError — DNS is down; 1.5s won't fix it.
        The circuit breaker in AlpacaClient handles the longer back-off.

    Errors that ARE retried (5xx, timeout, etc.):
      • HTTP 5xx  — server-side transient errors
      • Timeout   — may clear on next attempt
      • Any other unexpected exception
    """
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except requests.exceptions.HTTPError as exc:
            # 4xx = permanent client error — don't retry
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                logger.warning(
                    "HTTP %d — not retrying (client error): %s",
                    exc.response.status_code, exc,
                )
                raise
            logger.warning("Attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay * attempt)
        except requests.exceptions.ConnectionError as exc:
            # DNS / network-down errors — fail fast; circuit breaker handles back-off
            logger.warning("ConnectionError — not retrying (network issue): %s", exc)
            raise
        except Exception as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay * attempt)


# ── Alpaca circuit breaker ────────────────────────────────────────────────────
# After _CB_THRESHOLD consecutive connection failures, all Alpaca calls return
# immediately (no network attempt) until _CB_COOLDOWN seconds have elapsed.

_CB_THRESHOLD   = 3      # consecutive failures before opening the circuit
_CB_COOLDOWN    = 300    # seconds to wait before probing again (5 min — was 60s,
                         # which caused a "try → fail → log ERROR → wait 60s" loop
                         # every minute, flooding the Network tab all day)
_cb_fail_count  = 0      # consecutive connection failure count
_cb_open_until  = 0.0    # epoch time when circuit may close


class _AlpacaCircuitOpenError(Exception):
    """
    Raised by _get() when the circuit breaker is active.
    Callers catch this specifically so they can skip silently (the CB is
    already doing its job — no need to log it as an error every 5 minutes).
    """

def _cb_record_success():
    global _cb_fail_count, _cb_open_until
    _cb_fail_count = 0
    _cb_open_until = 0.0
    try:
        from broker_health import record_broker_success
        record_broker_success("alpaca")
    except Exception:
        pass

def _cb_record_failure():
    global _cb_fail_count, _cb_open_until
    _cb_fail_count += 1
    if _cb_fail_count >= _CB_THRESHOLD:
        _cb_open_until = time.time() + _CB_COOLDOWN
        logger.warning(
            "alpaca_circuit_open: %d consecutive connection failures — "
            "pausing Alpaca calls for %ds",
            _cb_fail_count, _CB_COOLDOWN,
        )
    # 2026-07-31: feed the dashboard alert banner — see broker_health.py.
    try:
        from broker_health import record_broker_error
        record_broker_error("alpaca", f"{_cb_fail_count} consecutive connection failures")
    except Exception:
        pass  # never let alerting itself break a trade path

def _cb_is_open() -> bool:
    """Return True if the circuit is open (calls should be skipped)."""
    if _cb_open_until and time.time() < _cb_open_until:
        return True
    return False


# ── Alpaca client ─────────────────────────────────────────────────────────────

def is_phantom_position_rejection(reason: Optional[str]) -> bool:
    """
    True only for the one Alpaca rejection message that unambiguously means
    "you don't actually hold this position" — i.e. a sell_to_close order
    where Alpaca infers sell_to_open because it has no matching long to
    close against. This is NOT a transient/retry-worthy failure (unlike
    e.g. insufficient buying power, which might resolve on its own) —
    retrying it will never succeed, so callers should stop retrying and
    reconcile the DB trade instead of looping forever.

    FIX 2026-07-17: built after trade #163 (INTC $120 call) got stuck
    retrying an exit every ~1s for hours — the position was fabricated by
    the now-fixed paper-fill bug and never existed at the broker, so no
    amount of retrying the close would ever succeed.
    """
    if not reason:
        return False
    r = reason.lower()
    return "position intent mismatch" in r and "sell_to_open" in r


def _extract_partial_fill(order: dict, fallback_price: Optional[float]) -> Optional[dict]:
    """
    Build a usable fill-result dict for an order that ended in a non-"filled"
    terminal state (canceled/expired/rejected/etc.) but still has SOME real
    fill on it. Returns None if filled_qty is 0 — i.e. truly nothing filled,
    safe for callers to treat as a no-op.

    FIX 2026-07-20 (Alpaca fills audit): `_wait_for_fill` previously only
    recognized `status == "filled"` as "something filled" — any other status
    (including "partially_filled" that later got cancelled/expired) was
    treated as if NOTHING happened. But a partial fill is a REAL position at
    the broker; dropping it silently caused the bot's records to diverge from
    Alpaca (either missing the position entirely, or, on retry, resubmitting
    the full original qty on top of it). This helper is the single place that
    decides "is there a real partial fill here worth keeping."
    """
    filled_qty = int(float(order.get("filled_qty") or 0))
    if filled_qty <= 0:
        return None
    filled_price = float(order.get("filled_avg_price") or fallback_price or 0)
    order["confirmed_fill_price"] = filled_price
    order["filled_qty"] = filled_qty
    order["partial_fill"] = True
    return order


