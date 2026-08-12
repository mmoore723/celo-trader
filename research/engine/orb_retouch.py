"""Causal one-minute opening-range breakout and first-retest primitives.

The opening range is the high and low of the first fifteen completed
one-minute bars (09:30 through 09:44 ET).  A later *completed* minute must
close beyond that range to establish direction.  Entry is intentionally not
made on that close: execution waits for the first subsequent retouch of the
broken boundary.

This module has no broker or database dependency.  The live layer supplies
the current quote for the retouch, while research can supply a later bar/quote
at the same point in time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Sequence

from research.engine.models import Bar, Side, Signal


OPENING_START = time(9, 30)
OPENING_END = time(9, 45)  # exclusive


@dataclass(frozen=True)
class OpeningRangeBreakoutContext:
    side: Side
    range_high: float
    range_low: float
    breakout_time: datetime
    breakout_close: float

    @property
    def retouch_level(self) -> float:
        return self.range_high if self.side is Side.LONG else self.range_low


def opening_range_from_one_minute_bars(bars: Sequence[Bar]) -> tuple[float, float] | None:
    """Return a range only when all fifteen opening minutes are present.

    Missing data is not filled or approximated.  A partial first fifteen
    minutes is not a valid opening range.
    """
    if not bars:
        return None
    day = bars[-1].timestamp.date()
    session = [bar for bar in bars if bar.timestamp.date() == day]
    anchor = session[-1].timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    expected = [anchor + timedelta(minutes=index) for index in range(15)]
    opening = [bar for bar in session if OPENING_START <= bar.timestamp.time() < OPENING_END]
    if [bar.timestamp for bar in opening] != expected:
        return None
    return max(bar.high for bar in opening), min(bar.low for bar in opening)


def first_close_confirmed_breakout(
    bars: Sequence[Bar], *, breakout_buffer_pct: float = 0.0,
    entry_deadline: time = time(11, 0),
) -> OpeningRangeBreakoutContext | None:
    """Find the first post-range completed-minute close beyond the range.

    The returned context is an *armed setup*, never an entry by itself.  A
    quote must later retouch ``retouch_level`` before the live execution layer
    can create an order-facing signal.
    """
    if not 0.0 <= breakout_buffer_pct < 0.01:
        raise ValueError("breakout_buffer_pct must be in [0, 0.01)")
    opening = opening_range_from_one_minute_bars(bars)
    if opening is None:
        return None
    high, low = opening
    day = bars[-1].timestamp.date()
    for bar in bars:
        if bar.timestamp.date() != day or not (OPENING_END <= bar.timestamp.time() <= entry_deadline):
            continue
        buffer = bar.close * breakout_buffer_pct
        if bar.close > high + buffer:
            return OpeningRangeBreakoutContext(Side.LONG, high, low, bar.timestamp, bar.close)
        if bar.close < low - buffer:
            return OpeningRangeBreakoutContext(Side.SHORT, high, low, bar.timestamp, bar.close)
    return None


def retouch_status(context: OpeningRangeBreakoutContext, price: float, *, tolerance_pct: float = 0.0005) -> str:
    """Classify a live price after an opening-range breakout.

    ``ready`` means price has not yet returned.  ``touch`` means it entered a
    narrow zone around the broken level and is eligible for an immediate entry.
    ``failed`` means it travelled through that zone far enough that treating it
    as a clean first retest would be chasing a failed breakout.
    """
    if price <= 0 or not 0.0 <= tolerance_pct < 0.01:
        raise ValueError("price must be positive and tolerance_pct must be in [0, 0.01)")
    level = context.retouch_level
    tolerance = max(level * tolerance_pct, 0.01)
    if context.side is Side.LONG:
        if price < level - tolerance:
            return "failed"
        if price <= level + tolerance:
            return "touch"
    else:
        if price > level + tolerance:
            return "failed"
        if price >= level - tolerance:
            return "touch"
    return "ready"


def one_minute_first_retouch_signals(
    bars: Sequence[Bar], *, tolerance_pct: float = 0.0005,
    entry_deadline: time = time(11, 0),
) -> tuple[Signal, ...]:
    """Return a conservative one-minute-bar proxy for the live retouch rule.

    The live bot arms after a *completed* breakout minute, then enters on the
    first later quote that returns to the broken opening-range boundary. A
    historical OHLC minute does not reveal the tick-by-tick order inside that
    minute, so this helper counts only a **clean** retouch: its low/high
    reaches the retouch zone without travelling through the invalidation side.
    That is intentionally stricter than the live quote path and every report
    using it must identify itself as a one-minute-bar proxy, not a tick replay.
    """
    if not 0.0 <= tolerance_pct < 0.01:
        raise ValueError("tolerance_pct must be in [0, 0.01)")
    by_day: dict[object, list[Bar]] = {}
    for bar in bars:
        by_day.setdefault(bar.timestamp.date(), []).append(bar)

    signals: list[Signal] = []
    for session in by_day.values():
        session.sort(key=lambda bar: bar.timestamp)
        opening = opening_range_from_one_minute_bars(session)
        if opening is None:
            continue
        range_high, range_low = opening
        context: OpeningRangeBreakoutContext | None = None
        terminal = False
        prior: Bar | None = None
        for bar in session:
            # This historical proxy cannot reconstruct a price move through a
            # missing minute. Stop the session at its first gap rather than
            # quietly treating a later retouch as the first clean retouch.
            if prior is not None and bar.timestamp - prior.timestamp != timedelta(minutes=1):
                break
            prior = bar
            if bar.timestamp.time() < OPENING_END or bar.timestamp.time() > entry_deadline:
                continue
            if context is None:
                if bar.close > range_high:
                    context = OpeningRangeBreakoutContext(Side.LONG, range_high, range_low, bar.timestamp, bar.close)
                elif bar.close < range_low:
                    context = OpeningRangeBreakoutContext(Side.SHORT, range_high, range_low, bar.timestamp, bar.close)
                continue

            # A retouch can only occur in a *later* minute than its completed
            # breakout confirmation.  This mirrors the live sequence.
            if terminal or bar.timestamp <= context.breakout_time:
                continue
            level = context.retouch_level
            tolerance = max(level * tolerance_pct, 0.01)
            if context.side is Side.LONG:
                if bar.low < level - tolerance:
                    terminal = True
                    continue
                touched = bar.low <= level + tolerance
                stop, target = range_low, level + 2 * (level - range_low)
            else:
                if bar.high > level + tolerance:
                    terminal = True
                    continue
                touched = bar.high >= level - tolerance
                stop, target = range_high, level - 2 * (range_high - level)
            if not touched:
                continue
            signals.append(Signal(
                strategy_id="V2_ORB_PULLBACK_1M_RETOUCH_PROXY",
                side=context.side,
                timestamp=bar.timestamp,
                entry_reference=level,
                stop=stop,
                target=target,
                features={
                    "entry_model": "completed_1m_breakout_then_clean_1m_retouch_proxy",
                    "breakout_time": context.breakout_time.isoformat(),
                    "retest_level": level,
                    "or_high": range_high,
                    "or_low": range_low,
                    "tolerance_pct": tolerance_pct,
                },
            ))
            terminal = True
    return tuple(signals)
