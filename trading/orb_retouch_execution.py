"""Paper-execution bridge for the one-minute V2 TSLA ORB retouch.

The strategy is deliberately split in two: completed one-minute bars establish
the breakout, and the current quote detects its first retouch.  This prevents
the bot from entering on a breakout close or waiting for an extra candle close.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import MutableMapping

import pandas as pd

from strategies.market_structure import Bar, Side, first_close_confirmed_breakout, retouch_status
from strategies.base import Signal


STRATEGY_ID = "V2_ORB_PULLBACK"
TICKER = "TSLA"
RETOUCH_TOLERANCE_PCT = 0.0005


def _completed_bars(today: pd.DataFrame, now: datetime) -> tuple[Bar, ...]:
    """Return only minutes that were fully closed before ``now``.

    Broker bar endpoints sometimes include the currently forming minute.  It
    is valid for a live *quote* to touch a level mid-minute, but it is never
    valid to use that same unfinished minute as breakout confirmation.
    """
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(today.columns):
        return ()
    rows = today.sort_values("time").drop_duplicates("time")
    times = pd.to_datetime(rows["time"])
    cutoff = pd.Timestamp(now).floor("min")
    source_tz = getattr(times.dt, "tz", None)
    if source_tz is None and cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    elif source_tz is not None and cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(source_tz)
    elif source_tz is not None:
        cutoff = cutoff.tz_convert(source_tz)
    rows = rows.loc[times < cutoff]
    return tuple(
        Bar(pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
            float(row.low), float(row.close), float(getattr(row, "volume", 0.0)))
        for row in rows.itertuples(index=False)
    )


def update_one_minute_orb_retouch(
    state: MutableMapping[str, object], today: pd.DataFrame, *, ticker: str,
    quote_price: float | None, now: datetime,
) -> tuple[Signal | None, str]:
    """Advance one session's ORB state and return a one-time retouch signal.

    This function is pure with respect to brokerage: the caller persists the
    small supplied state dictionary and routes any returned signal normally.
    """
    if ticker.strip().upper() != TICKER or quote_price is None or quote_price <= 0:
        return None, "not_applicable"
    bars = _completed_bars(today, now)
    if not bars:
        return None, "waiting_for_bars"
    trading_day = bars[-1].timestamp.date().isoformat()
    key = f"{ticker.upper()}:{trading_day}"
    if state.get("key") != key:
        state.clear()
        state["key"] = key
    if state.get("terminal"):
        return None, str(state["terminal"])

    context = first_close_confirmed_breakout(bars)
    if context is None:
        return None, "building_or_waiting_for_breakout"
    state["breakout_time"] = context.breakout_time.isoformat()
    state["side"] = context.side.value
    state["retouch_level"] = context.retouch_level
    status = retouch_status(context, float(quote_price), tolerance_pct=RETOUCH_TOLERANCE_PCT)
    if status == "ready":
        return None, "armed_waiting_for_first_retouch"
    if status == "failed":
        state["terminal"] = "failed_retouch"
        return None, "failed_retouch"

    # A quote can only trigger after a completed breakout minute.  The entry
    # is the quote at first retouch—not its minute's later close.
    state["terminal"] = "emitted"
    stop = context.range_low if context.side is Side.LONG else context.range_high
    risk = abs(float(quote_price) - stop)
    if risk <= 0:
        state["terminal"] = "invalid_risk"
        return None, "invalid_risk"
    direction = "bullish" if context.side is Side.LONG else "bearish"
    target = float(quote_price) + 2 * risk if context.side is Side.LONG else float(quote_price) - 2 * risk
    return Signal(
        confidence=0.80,
        strategy_id=STRATEGY_ID,
        direction=direction,
        rvol=float(today.iloc[-1].get("rvol", 0.0) or 0.0),
        trigger_bar=pd.Timestamp(now),
        meta={
            "v2_hypothesis": "one_minute_opening_range_first_retouch",
            "research_only": True,
            "entry_timing": "completed_1m_breakout_then_live_quote_first_retouch",
            "or_high": context.range_high,
            "or_low": context.range_low,
            "breakout_time": context.breakout_time.isoformat(),
            "retest_level": context.retouch_level,
            "quote_entry_reference": float(quote_price),
            "v2_entry_reference": float(quote_price),
            "v2_stop": stop,
            "v2_target": target,
            "entry_bar_low": stop if context.side is Side.LONG else None,
            "entry_bar_high": stop if context.side is Side.SHORT else None,
        },
    ), "first_retouch_quote"
