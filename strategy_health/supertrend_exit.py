"""Continue the exact SuperTrend engine from the state at its entry signal.

The original reversal simulator fills an opposite flip at the next bar open.
Its 15:55 bar is flattened at its CLOSE (16:00); a pending 15:55 entry/flip
is discarded. Placeholder Signal.stop/target fields are never exits here.
"""
from datetime import timedelta
from functools import lru_cache
import hashlib
import inspect
import math

from research.engine.models import Bar, Side
from research.engine.strategies.supertrend_reversal import SuperTrendReversal
from strategy_health.impulse_exit import et

STRATEGY_ID = "TV_SUPERTREND_REVERSAL_V4"
PROTOCOL = "supertrend_opposite_flip_completed5m_v1"


@lru_cache(maxsize=1)
def engine_hash():
    return hashlib.sha256(inspect.getsource(SuperTrendReversal).encode()).hexdigest()


def entry_state(strategy):
    """Save only the sufficient RMA state, not hundreds of historical bars."""
    return {
        "engine_hash": engine_hash(), "bar_time": et(strategy._last_timestamp).isoformat(),
        "atr": strategy._atr_value, "close": strategy._last_close,
        "up": strategy._up, "down": strategy._down, "trend": strategy._trend,
        "period": strategy.config.atr_period, "multiplier": strategy.config.multiplier,
        "rma": strategy.config.use_rma_atr,
    }


def restored(seed, entry, direction):
    try:
        if (seed["engine_hash"] != engine_hash() or seed["period"] != 10
                or seed["multiplier"] != 3 or seed["rma"] is not True
                or seed["trend"] != (1 if direction == "bullish" else -1)
                or et(seed["bar_time"]) + timedelta(minutes=5) != entry):
            return None
        if not all(math.isfinite(float(seed[k])) for k in ("atr", "close", "up", "down")):
            return None
        if seed["atr"] <= 0 or seed["close"] <= 0:
            return None
        strategy = SuperTrendReversal()
        strategy._atr_value, strategy._last_close = seed["atr"], seed["close"]
        strategy._up, strategy._down, strategy._trend = seed["up"], seed["down"], seed["trend"]
        strategy._last_timestamp, strategy._seen = et(seed["bar_time"]), 10
        # Warm-up is already complete. RMA needs its last value, not old TRs.
        strategy._tr_values = [0.0] * 10
        return strategy
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def first_exit(frame, *, entry_at, entry_quote_at, direction, seed, now):
    entry, now = et(entry_at), et(now)
    if direction not in {"bullish", "bearish"} or entry.minute % 5 or entry.second or entry.microsecond:
        return entry, "invalid_entry"
    if not entry.replace(hour=9, minute=30) <= entry < entry.replace(hour=15, minute=55):
        return entry, "entry_after_session_cutoff"
    if not entry <= et(entry_quote_at) < entry + timedelta(minutes=5):
        return entry, "late_entry_quote"
    engine = restored(seed, entry, direction)
    if engine is None:
        return entry, "missing_indicator_state"
    rows = {}
    for row in frame.to_dict("records"):
        stamp = et(row["time"])
        if stamp in rows:
            return entry, "duplicate_bars"
        rows[stamp] = row
    start = entry
    closing_bar = entry.replace(hour=15, minute=55)
    side = Side.LONG if direction == "bullish" else Side.SHORT
    while start < closing_bar and start + timedelta(minutes=5) <= now:
        decision = start + timedelta(minutes=5)
        bucket = [rows.get(start + timedelta(minutes=i)) for i in range(5)]
        if any(r is None for r in bucket):
            return (decision, "missing_bars") if now > decision + timedelta(minutes=5) else None
        values = [[float(r[k]) for k in ("open", "high", "low", "close")] for r in bucket]
        for o, h, low, c in values:
            if not all(math.isfinite(v) and v > 0 for v in (o, h, low, c)) or not low <= min(o, c) <= max(o, c) <= h:
                return decision, "invalid_bars"
        bar = Bar(start, values[0][0], max(v[1] for v in values), min(v[2] for v in values), values[-1][3])
        signal = engine._advance(bar)
        if signal is not None and signal.side is not side and decision < closing_bar:
            return decision, "opposite_flip"
        start = decision
    if start >= closing_bar and now >= closing_bar + timedelta(minutes=5):
        return closing_bar + timedelta(minutes=5), "session_flatten"
    return None
