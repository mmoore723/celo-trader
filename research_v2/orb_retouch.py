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

from research_v2.models import Bar, Side


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
