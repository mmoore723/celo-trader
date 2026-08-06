"""Causal, underlying-driven exit clocks for executable option research.

These rules do not model an option fill.  They decide *when* an exit should be
attempted from completed underlying bars.  ``option_markouts`` then looks for
the first real bid on the already-selected option contract at that time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Sequence

from research_v2.models import Bar, Side, Signal


@dataclass(frozen=True)
class PlannedExit:
    """A causal exit decision, including the fallback time cap."""

    label: str
    time: object
    reason: str


def _session_bars(bars: Sequence[Bar], current: Bar) -> tuple[Bar, ...]:
    return tuple(bar for bar in bars if bar.timestamp.date() == current.timestamp.date()
                 and bar.timestamp <= current.timestamp)


def _vwap(bars: Sequence[Bar]) -> float:
    volume = sum(max(bar.volume, 1.0) for bar in bars)
    return sum(((bar.high + bar.low + bar.close) / 3.0) * max(bar.volume, 1.0)
               for bar in bars) / volume


def _ema(closes: Sequence[float], length: int) -> float:
    value = closes[0]
    alpha = 2.0 / (length + 1.0)
    for close in closes[1:]:
        value = alpha * close + (1.0 - alpha) * value
    return value


def planned_exits(
    bars: Iterable[Bar], signal: Signal, entry_bar: Bar, *, hold_minutes: int = 90,
    ema_length: int = 9,
) -> dict[str, PlannedExit]:
    """Return predeclared VWAP/EMA loss exits plus the same fixed time cap.

    A long exits when a *later completed* five-minute bar closes at or below
    VWAP/EMA; a short reverses that comparison.  Every dynamic rule falls back
    to the 90-minute cap.  The decision time is the end of the confirming bar,
    so the test never assumes it could trade on information from an unfinished
    bar.
    """
    completed = tuple(bars)
    if hold_minutes < 1 or ema_length < 2:
        raise ValueError("hold_minutes must be positive and ema_length must be at least 2")
    cap = entry_bar.timestamp + timedelta(minutes=hold_minutes)
    plans = {
        "fixed_90m": PlannedExit("fixed_90m", cap, "time_cap_90m"),
        "vwap_loss_90m": PlannedExit("vwap_loss_90m", cap, "time_cap_90m"),
        "ema9_loss_90m": PlannedExit("ema9_loss_90m", cap, "time_cap_90m"),
        "vwap_or_ema9_90m": PlannedExit("vwap_or_ema9_90m", cap, "time_cap_90m"),
    }
    later = [bar for bar in completed if entry_bar.timestamp < bar.timestamp <= cap
             and bar.timestamp.date() == entry_bar.timestamp.date()]
    for bar in later:
        session = _session_bars(completed, bar)
        if len(session) < ema_length:
            continue
        vwap_lost = bar.close <= _vwap(session) if signal.side is Side.LONG else bar.close >= _vwap(session)
        ema_lost = bar.close <= _ema([item.close for item in session], ema_length) if signal.side is Side.LONG else bar.close >= _ema([item.close for item in session], ema_length)
        # A five-minute bar timestamp represents its opening instant in this
        # research feed.  The close is only known five minutes later.
        decision_time = bar.timestamp + timedelta(minutes=5)
        if vwap_lost and plans["vwap_loss_90m"].reason == "time_cap_90m":
            plans["vwap_loss_90m"] = PlannedExit("vwap_loss_90m", decision_time, "vwap_loss")
        if ema_lost and plans["ema9_loss_90m"].reason == "time_cap_90m":
            plans["ema9_loss_90m"] = PlannedExit("ema9_loss_90m", decision_time, "ema9_loss")
        if (vwap_lost or ema_lost) and plans["vwap_or_ema9_90m"].reason == "time_cap_90m":
            reason = "vwap_loss" if vwap_lost else "ema9_loss"
            plans["vwap_or_ema9_90m"] = PlannedExit("vwap_or_ema9_90m", decision_time, reason)
    return plans
