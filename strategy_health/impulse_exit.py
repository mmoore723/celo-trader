"""Frozen Impulse exit measurement, not an executable order policy.

Matches replay_paid_tsla_impulse_anchored_vwap_exits.intended_exit_plan:
skip the entry candle, inspect completed 5m bars, stop wins ambiguous bars.
The 24-bar hold cap is decided at bar CLOSE (entry open + 125 minutes).
"""
from datetime import datetime, timedelta
import math

import pandas as pd

from database.helpers import _to_et_isoformat

STRATEGY_ID = "V2_IMPULSE_ANCHORED_VWAP_PULLBACK"
PROTOCOL = "impulse_structural_2r_completed5m_v1"


def et(value):
    return datetime.fromisoformat(_to_et_isoformat(value))


def first_exit(frame, *, entry_at, entry_quote_at, stop, target, direction, now,
               max_hold_bars=24, time_cap_reason="time_cap_120m"):
    """Return (decision time, reason), or None while still observing.

    Missing input is explicitly unmeasurable, not a made-up stop or a win.
    Five minutes are allowed for delayed bars before closing that evidence gap.
    """
    entry, now = et(entry_at), et(now)
    if (entry.minute % 5 or entry.second or entry.microsecond
            or not entry.replace(hour=9, minute=30) <= entry < entry.replace(hour=16, minute=0)):
        return entry, "invalid_entry"
    if not entry <= et(entry_quote_at) < entry + timedelta(minutes=5):
        return entry, "late_entry_quote"
    try:
        stop, target = float(stop), float(target)
    except (TypeError, ValueError, OverflowError):
        return entry, "invalid_levels"
    if (direction not in {"bullish", "bearish"}
            or not all(math.isfinite(v) and v > 0 for v in (stop, target))
            or (direction == "bullish" and stop >= target)
            or (direction == "bearish" and stop <= target)):
        return entry, "invalid_levels"
    rows = {}
    for row in frame.to_dict("records"):
        stamp = et(row["time"])
        if stamp in rows:
            return entry, "duplicate_bars"
        rows[stamp] = row
    bar_start = entry + timedelta(minutes=5)
    deadline = min(entry + timedelta(minutes=5*(max_hold_bars+1)), entry.replace(hour=16, minute=0))
    while bar_start + timedelta(minutes=5) <= min(now, deadline):
        decision = bar_start + timedelta(minutes=5)
        bucket = [rows.get(bar_start + timedelta(minutes=i)) for i in range(5)]
        if any(row is None for row in bucket):
            return (decision, "missing_bars") if now > decision + timedelta(minutes=5) else None
        for row in bucket:
            try:
                values = [float(row[k]) for k in ("open", "high", "low", "close")]
            except (TypeError, ValueError, KeyError, OverflowError):
                return decision, "invalid_bars"
            o, h, low, c = values
            if not all(math.isfinite(v) and v > 0 for v in values) or not low <= min(o, c) <= max(o, c) <= h:
                return decision, "invalid_bars"
        high, low = max(float(r["high"]) for r in bucket), min(float(r["low"]) for r in bucket)
        stopped = low <= stop if direction == "bullish" else high >= stop
        targeted = high >= target if direction == "bullish" else low <= target
        if stopped:
            return decision, "underlying_stop"
        if targeted:
            return decision, "underlying_2r_target"
        if decision.hour == 16:
            return decision, "session_flatten"
        if decision >= deadline:
            return decision, time_cap_reason
        bar_start = decision
    if now >= deadline and bar_start >= deadline:
        return deadline, "end_of_available_session"
    return None


def executable_bid(quote, *, contract, decision_at, received_at):
    """Only a fresh same-contract bid after the exit decision can price it."""
    try:
        decision, received = et(decision_at), et(received_at)
        bid, ask = float(quote["bid"]), float(quote["ask"])
        stamp = quote["bid_date"]
        if isinstance(stamp, (int, float)):
            stamp = pd.Timestamp(stamp, unit="ms", tz="UTC").to_pydatetime()
        bid_time = et(stamp)
        valid = (
            quote.get("symbol") == contract and quote.get("source_symbol") == contract
            and math.isfinite(bid) and math.isfinite(ask)
            and 0 <= bid <= ask and ask > 0
            and decision <= bid_time <= received <= decision + timedelta(minutes=5)
            and (received - bid_time).total_seconds() <= 120
        )
        return (bid, bid_time.isoformat()) if valid else None
    except (TypeError, ValueError, KeyError, OverflowError, AttributeError):
        return None
