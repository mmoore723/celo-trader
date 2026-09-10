"""Frozen Opening Momentum trail; one-minute stop observations, not stop fills.

Preserves Simulator ordering: skip entry candle; inspect the old stop first;
tighten at the five-minute close for the NEXT candle only. A stop touch is
observable at the close of its first one-minute candle. Its option bid must
be captured separately; the underlying simulator's stop price is not a fill.
"""
from datetime import timedelta
from functools import lru_cache
import hashlib
import inspect
import math

from research.engine.models import Bar, Side, Signal
from research.engine.simulator import Simulator, SimulationConfig, _Position
from research.engine.strategies.opening_momentum_rth import OpeningMomentumRTH
from research.engine.strategies.gap_fill_rth import _atr
from strategy_health.impulse_exit import et

STRATEGY_ID = "V2_OPENING_MOMENTUM_RTH_EXPLORATORY"
PROTOCOL = "opening_momentum_2atr_5m_trail_1m_observation_v1"
LOW_WATER_PROTOCOL = "opening_momentum_2atr_short_low_water_1m_observation_v1"


@lru_cache(maxsize=1)
def engine_hash():
    source = '\n'.join(inspect.getsource(x) for x in (
        OpeningMomentumRTH, _atr, Simulator, SimulationConfig,
    ))
    return hashlib.sha256(source.encode()).hexdigest()


def entry_state(strategy, *, fingerprint=None):
    return {
        "engine_hash": fingerprint or engine_hash(), "atr_period": strategy.config.atr_bars,
        "trail_multiple": strategy.config.atr_trail_multiple,
        "history": [[et(b.timestamp).isoformat(), b.open, b.high, b.low, b.close]
                    for b in strategy._history[-15:]],
    }


def valid_bar(stamp, values):
    o, high, low, close = (float(v) for v in values)
    if not all(math.isfinite(v) and v > 0 for v in (o, high, low, close)):
        raise ValueError("Non-finite OHLC")
    return Bar(et(stamp), o, high, low, close)


def restored(seed, entry, *, engine_factory=OpeningMomentumRTH, fingerprint=None):
    try:
        if seed["engine_hash"] != (fingerprint or engine_hash()) or seed["atr_period"] != 14 or seed["trail_multiple"] != 2:
            return None
        bars = [valid_bar(row[0], row[1:]) for row in seed["history"]]
        if len(bars) != 15 or bars[-1].timestamp + timedelta(minutes=5) != entry:
            return None
        if any(a.timestamp >= b.timestamp for a, b in zip(bars, bars[1:])):
            return None
        engine = engine_factory()
        engine._history = bars
        return engine
    except (TypeError, ValueError, KeyError, AttributeError, IndexError):
        return None


def first_exit(frame, *, entry_at, entry_quote_at, direction, seed, stop, target, now,
               short_low_water=False, restore_engine=None, strategy_id=STRATEGY_ID):
    entry, now = et(entry_at), et(now)
    if (direction not in {"bullish", "bearish"} or entry.minute % 5 or entry.second or entry.microsecond
            or not entry.replace(hour=9, minute=30) <= entry < entry.replace(hour=16, minute=0)):
        return entry, "invalid_entry"
    if not entry <= et(entry_quote_at) < entry + timedelta(minutes=5):
        return entry, "late_entry_quote"
    engine = (restore_engine or restored)(seed, entry)
    if engine is None:
        return entry, "missing_indicator_state"
    try:
        side = Side.LONG if direction == "bullish" else Side.SHORT
        if not all(math.isfinite(float(v)) for v in (stop, target)):
            raise ValueError("Invalid levels")
        signal = Signal(strategy_id, side, entry-timedelta(minutes=5), engine._history[-1].close,
                        stop, target, {"no_profit_target": True})
    except (TypeError, ValueError):
        return entry, "invalid_levels"
    rows = {}
    for row in frame.to_dict("records"):
        stamp = et(row["time"])
        if stamp in rows:
            return entry, "duplicate_bars"
        rows[stamp] = row
    start, position = entry, None
    while start < entry.replace(hour=16, minute=0):
        minutes = []
        for i in range(5):
            stamp = start + timedelta(minutes=i)
            observed = stamp + timedelta(minutes=1)
            if observed > now:
                return None
            row = rows.get(stamp)
            if row is None:
                return (observed, "missing_bars") if now > observed + timedelta(minutes=5) else None
            try:
                minute = valid_bar(stamp, [row[k] for k in ("open", "high", "low", "close")])
            except (TypeError, ValueError, KeyError):
                return observed, "invalid_bars"
            minutes.append(minute)
            if position is not None:
                touched = minute.low <= position.active_stop if side is Side.LONG else minute.high >= position.active_stop
                if touched:
                    return observed, "atr_trailing_stop"
        bar = Bar(start, minutes[0].open, max(b.high for b in minutes), min(b.low for b in minutes), minutes[-1].close)
        completed_at = start + timedelta(minutes=5)
        if position is None:
            # Preserve the frozen simulator's reference entry anchor, but not
            # its allocation limit: every research play gets measured.
            modeled_entry = bar.open * (1.0005 if side is Side.LONG else .9995)
            position = _Position(signal, entry, modeled_entry, 1, 0, modeled_entry, modeled_entry, stop)
        else:
            position.best_price = max(position.best_price, bar.high)
            position.worst_price = min(position.worst_price, bar.low)
            if (start-entry).total_seconds() >= 75*300:
                return completed_at, "time_cap_75bars"
            if start.hour == 15 and start.minute == 55:
                return completed_at, "session_flatten"
            if short_low_water and side is Side.SHORT:
                candidate = engine.trailing_stop(signal, position.active_stop, bar, position.worst_price)
                if candidate is not None and signal.target < candidate < position.active_stop:
                    position.active_stop = candidate
            else:
                Simulator._tighten_trailing_stop(engine, position, bar)
        engine._history = (engine._history + [bar])[-15:]
        start = completed_at
    return (start, "end_of_available_session") if now >= start else None
