"""Causal, underlying-driven exit clocks for executable option research.

These rules do not model an option fill.  They decide *when* an exit should be
attempted from completed underlying bars.  ``option_markouts`` then looks for
the first real bid on the already-selected option contract at that time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Iterable, Sequence

from research.engine.models import Bar, Side, Signal


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


def planned_dynamic_exits(
    bars: Iterable[Bar], signal: Signal, entry_bar: Bar, *,
    chandelier_atr_multiple: float = 3.0,
    chandelier_cap_minutes: int = 75,
    confirmed_cap_minutes: int = 90,
    ema_length: int = 9,
) -> dict[str, PlannedExit]:
    """Plan a small, causal comparison of exits that react to price action.

    This is deliberately a *research* translation of the live simplified exit
    idea, not a broker command.  It uses the V2 signal's underlying structural
    stop, then compares three predeclared choices:

    ``live_like_chandelier_75m``
        Structural invalidation, then a 3 ATR Chandelier trail, then 75 min.
    ``confirmed_vwap_ema_90m``
        Structural invalidation, then two completed bars losing both VWAP and
        EMA(9), then 90 min.  Requiring two bars avoids exiting on one chop bar.
    ``hybrid_chandelier_vwap_ema_90m``
        Structural invalidation, the Chandelier, or the same two-bar
        VWAP/EMA confirmation, then 90 min.

    Every decision is made only after a bar is complete and is sent five
    minutes later.  The option research layer sells the selected contract at
    the first real bid after that decision time.
    """
    completed = tuple(bars)
    if (chandelier_atr_multiple <= 0 or chandelier_cap_minutes < 1
            or confirmed_cap_minutes < 1 or ema_length < 2):
        raise ValueError("invalid dynamic exit parameters")

    short_cap = entry_bar.timestamp + timedelta(minutes=chandelier_cap_minutes)
    long_cap = entry_bar.timestamp + timedelta(minutes=confirmed_cap_minutes)
    plans = {
        "fixed_90m": PlannedExit("fixed_90m", long_cap, "time_cap_90m"),
        "live_like_chandelier_75m": PlannedExit(
            "live_like_chandelier_75m", short_cap, "time_cap_75m"
        ),
        "confirmed_vwap_ema_90m": PlannedExit(
            "confirmed_vwap_ema_90m", long_cap, "time_cap_90m"
        ),
        "hybrid_chandelier_vwap_ema_90m": PlannedExit(
            "hybrid_chandelier_vwap_ema_90m", long_cap, "time_cap_90m"
        ),
    }
    peak = entry_bar.high if signal.side is Side.LONG else entry_bar.low
    prior_joint_loss = False
    latest_trail: float | None = None
    max_cap = max(short_cap, long_cap)
    later = [bar for bar in completed if entry_bar.timestamp < bar.timestamp <= max_cap
             and bar.timestamp.date() == entry_bar.timestamp.date()]

    for bar in later:
        session = _session_bars(completed, bar)
        decision_time = bar.timestamp + timedelta(minutes=5)
        in_short_window = bar.timestamp <= short_cap
        in_long_window = bar.timestamp <= long_cap
        structural_lost = (
            bar.low <= signal.stop if signal.side is Side.LONG else bar.high >= signal.stop
        )

        # The same basic Chandelier idea as the simplified live path: trail
        # the strongest underlying price seen since entry by 3 ATR.  The V2
        # strategy's ATR is recomputed only from completed underlying bars.
        if signal.side is Side.LONG:
            peak = max(peak, bar.high)
        else:
            peak = min(peak, bar.low)
        trail_lost = False
        if len(session) >= 15:
            atr = _atr_for_exit(session, 14)
            proposed = (peak - chandelier_atr_multiple * atr if signal.side is Side.LONG
                        else peak + chandelier_atr_multiple * atr)
            if latest_trail is None:
                latest_trail = proposed
            elif signal.side is Side.LONG:
                latest_trail = max(latest_trail, proposed)
            else:
                latest_trail = min(latest_trail, proposed)
            trail_lost = (bar.low <= latest_trail if signal.side is Side.LONG
                          else bar.high >= latest_trail)

        joint_loss = False
        if len(session) >= ema_length:
            vwap_lost = (bar.close <= _vwap(session) if signal.side is Side.LONG
                         else bar.close >= _vwap(session))
            ema_lost = (bar.close <= _ema([item.close for item in session], ema_length)
                        if signal.side is Side.LONG
                        else bar.close >= _ema([item.close for item in session], ema_length))
            joint_loss = vwap_lost and ema_lost
        confirmed_loss = prior_joint_loss and joint_loss
        prior_joint_loss = joint_loss

        if in_short_window and plans["live_like_chandelier_75m"].reason == "time_cap_75m":
            if structural_lost:
                plans["live_like_chandelier_75m"] = PlannedExit(
                    "live_like_chandelier_75m", decision_time, "structural_stop"
                )
            elif trail_lost:
                plans["live_like_chandelier_75m"] = PlannedExit(
                    "live_like_chandelier_75m", decision_time, "chandelier_3atr"
                )
        if in_long_window and plans["confirmed_vwap_ema_90m"].reason == "time_cap_90m":
            if structural_lost:
                plans["confirmed_vwap_ema_90m"] = PlannedExit(
                    "confirmed_vwap_ema_90m", decision_time, "structural_stop"
                )
            elif confirmed_loss:
                plans["confirmed_vwap_ema_90m"] = PlannedExit(
                    "confirmed_vwap_ema_90m", decision_time, "confirmed_vwap_ema_loss"
                )
        if in_long_window and plans["hybrid_chandelier_vwap_ema_90m"].reason == "time_cap_90m":
            if structural_lost:
                plans["hybrid_chandelier_vwap_ema_90m"] = PlannedExit(
                    "hybrid_chandelier_vwap_ema_90m", decision_time, "structural_stop"
                )
            elif trail_lost:
                plans["hybrid_chandelier_vwap_ema_90m"] = PlannedExit(
                    "hybrid_chandelier_vwap_ema_90m", decision_time, "chandelier_3atr"
                )
            elif confirmed_loss:
                plans["hybrid_chandelier_vwap_ema_90m"] = PlannedExit(
                    "hybrid_chandelier_vwap_ema_90m", decision_time, "confirmed_vwap_ema_loss"
                )
    return plans


def planned_one_minute_dynamic_exits(
    bars: Iterable[Bar], signal: Signal, entry_bar: Bar, *,
    chandelier_atr_multiple: float = 3.0,
    cap_minutes: int = 90,
    ema_length: int = 9,
) -> dict[str, PlannedExit]:
    """Causal one-minute exit plans for the one-minute ORB retouch study.

    This is deliberately separate from :func:`planned_dynamic_exits`: its
    underlying bars are one minute long, so a completed-bar decision can be
    made one minute later, not five minutes later.  It compares a fixed cap,
    the original structural invalidation, a two-bar VWAP/EMA loss, and their
    combination.  It only plans *when* to sell; the option layer still uses
    the first real bid for the already-selected contract.
    """
    completed = tuple(bars)
    if chandelier_atr_multiple <= 0 or cap_minutes < 1 or ema_length < 2:
        raise ValueError("invalid one-minute exit parameters")
    cap = entry_bar.timestamp + timedelta(minutes=cap_minutes)
    # Keep the established 90-minute keys stable for existing TSLA reports;
    # non-default caps name themselves truthfully (for example fixed_60m).
    suffix = "_90m" if cap_minutes == 90 else f"_{cap_minutes}m"
    fixed_rule = "fixed_90m" if cap_minutes == 90 else f"fixed{suffix}"
    structural_rule = f"structural_stop{suffix}"
    confirmed_rule = f"confirmed_vwap_ema{suffix}"
    hybrid_rule = f"hybrid_stop_vwap_ema{suffix}"
    time_cap_reason = f"time_cap_{cap_minutes}m"
    plans = {
        fixed_rule: PlannedExit(fixed_rule, cap, time_cap_reason),
        structural_rule: PlannedExit(structural_rule, cap, time_cap_reason),
        confirmed_rule: PlannedExit(confirmed_rule, cap, time_cap_reason),
        hybrid_rule: PlannedExit(hybrid_rule, cap, time_cap_reason),
    }
    prior_joint_loss = False
    later = [bar for bar in completed if entry_bar.timestamp < bar.timestamp <= cap
             and bar.timestamp.date() == entry_bar.timestamp.date()]
    for bar in later:
        session = _session_bars(completed, bar)
        # The close of a one-minute bar is available at the next minute.
        decision_time = bar.timestamp + timedelta(minutes=1)
        structural_lost = (bar.low <= signal.stop if signal.side is Side.LONG
                           else bar.high >= signal.stop)
        joint_loss = False
        if len(session) >= ema_length:
            vwap_lost = (bar.close <= _vwap(session) if signal.side is Side.LONG
                         else bar.close >= _vwap(session))
            ema_lost = (bar.close <= _ema([item.close for item in session], ema_length)
                        if signal.side is Side.LONG else bar.close >= _ema([item.close for item in session], ema_length))
            joint_loss = vwap_lost and ema_lost
        confirmed_loss = prior_joint_loss and joint_loss
        prior_joint_loss = joint_loss
        if structural_lost:
            if plans[structural_rule].reason == time_cap_reason:
                plans[structural_rule] = PlannedExit(structural_rule, decision_time, "structural_stop")
            if plans[hybrid_rule].reason == time_cap_reason:
                plans[hybrid_rule] = PlannedExit(hybrid_rule, decision_time, "structural_stop")
        if confirmed_loss:
            if plans[confirmed_rule].reason == time_cap_reason:
                plans[confirmed_rule] = PlannedExit(confirmed_rule, decision_time, "confirmed_vwap_ema_loss")
            if plans[hybrid_rule].reason == time_cap_reason:
                plans[hybrid_rule] = PlannedExit(hybrid_rule, decision_time, "confirmed_vwap_ema_loss")
    return plans


def planned_noise_momentum_exits(
    bars: Iterable[Bar], signal: Signal, entry_bar: Bar, *,
    boundaries: dict[object, tuple[float, float]],
) -> dict[str, PlannedExit]:
    """Plan the published adaptive-band/VWAP exit for noise momentum.

    The signal premise is checked only at half-hour clocks, so exits are also
    evaluated only after completed bars at those clocks.  The force-close is
    scheduled for 15:59, one minute before the cash close: this is the latest
    executable point the one-minute underlying and quote dataset can support
    without pretending that the 15:59--16:00 candle was already complete.
    """
    completed = tuple(bars)
    session = tuple(
        bar for bar in completed if bar.timestamp.date() == entry_bar.timestamp.date()
    )
    if not session:
        raise ValueError("entry bar must belong to bars")
    close_time = entry_bar.timestamp.replace(hour=15, minute=59, second=0, microsecond=0)
    plans = {
        "fixed_preclose": PlannedExit("fixed_preclose", close_time, "preclose_1559"),
        "current_band": PlannedExit("current_band", close_time, "preclose_1559"),
        "current_band_vwap": PlannedExit("current_band_vwap", close_time, "preclose_1559"),
    }
    for bar in session:
        if bar.timestamp <= entry_bar.timestamp or bar.timestamp >= close_time:
            continue
        clock = bar.timestamp.time()
        if clock.minute not in (0, 30) or clock < time(10, 0) or clock > time(15, 30):
            continue
        boundary = boundaries.get(bar.timestamp)
        if boundary is None:
            continue
        lower, upper = boundary
        session_to_bar = _session_bars(session, bar)
        vwap = _vwap(session_to_bar)
        band_lost = bar.close < upper if signal.side is Side.LONG else bar.close > lower
        vwap_band_lost = (bar.close < max(upper, vwap) if signal.side is Side.LONG
                          else bar.close > min(lower, vwap))
        # The completed bar's close becomes known in the next minute.
        decision_time = bar.timestamp + timedelta(minutes=1)
        if band_lost and plans["current_band"].reason == "preclose_1559":
            plans["current_band"] = PlannedExit("current_band", decision_time, "lost_current_noise_boundary")
        if vwap_band_lost and plans["current_band_vwap"].reason == "preclose_1559":
            plans["current_band_vwap"] = PlannedExit(
                "current_band_vwap", decision_time, "lost_current_noise_boundary_or_vwap"
            )
    return plans


def _atr_for_exit(bars: Sequence[Bar], length: int) -> float:
    relevant = bars[-(length + 1):]
    if len(relevant) < length + 1:
        raise ValueError("not enough bars for ATR")
    ranges = [
        max(bar.high - bar.low, abs(bar.high - prior.close), abs(bar.low - prior.close))
        for prior, bar in zip(relevant, relevant[1:])
    ]
    return sum(ranges) / len(ranges)
