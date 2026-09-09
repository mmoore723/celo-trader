"""Predeclared one-minute exits for the TSLA Two-Leg research study.

The functions in this module only choose a causal exit time from completed
underlying candles.  They never place an order and never change the live or
paper strategy.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from research.engine.exit_rules import PlannedExit, _atr_for_exit, _ema, _session_bars, _vwap
from research.engine.models import Bar, Side, Signal


RULES = (
    "fixed_90m",
    "structural_stop_90m",
    "confirmed_vwap_ema_90m",
    "armed_chandelier_3atr_90m",
    "hybrid_armed_chandelier_vwap_ema_90m",
)


def planned_two_leg_dynamic_exits(
    bars: Iterable[Bar], signal: Signal, entry_bar: Bar, *, cap_minutes: int = 90,
    ema_length: int = 9, atr_length: int = 14, trail_atr_multiple: float = 3.0,
    arm_at_reward_risk: float = 1.0,
) -> dict[str, PlannedExit]:
    """Compare four dynamic exits with the unchanged fixed-time control.

    The trail arms only after a *completed close* reaches +1R.  It cannot exit
    on the arming candle.  Later completed closes are compared with a monotonic
    3-ATR Chandelier, preventing intraminute ordering assumptions.  Every
    dynamic rule retains the same 90-minute cap as the control.
    """
    completed = tuple(bars)
    if (cap_minutes < 1 or ema_length < 2 or atr_length < 2
            or trail_atr_multiple <= 0 or arm_at_reward_risk <= 0):
        raise ValueError("invalid Two-Leg dynamic exit parameters")
    cap = entry_bar.timestamp + timedelta(minutes=cap_minutes)
    cap_reason = f"time_cap_{cap_minutes}m"
    plans = {rule: PlannedExit(rule, cap, cap_reason) for rule in RULES}
    later = tuple(
        bar for bar in completed
        if entry_bar.timestamp < bar.timestamp < cap
        and bar.timestamp.date() == entry_bar.timestamp.date()
    )
    risk = abs(signal.entry_reference - signal.stop)
    if risk <= 0:
        raise ValueError("signal must have positive structural risk")
    arm_price = (
        signal.entry_reference + arm_at_reward_risk * risk
        if signal.side is Side.LONG
        else signal.entry_reference - arm_at_reward_risk * risk
    )
    extreme = entry_bar.high if signal.side is Side.LONG else entry_bar.low
    trail: float | None = None
    armed = False
    prior_joint_loss = False

    for bar in later:
        session = _session_bars(completed, bar)
        decision_time = bar.timestamp + timedelta(minutes=1)
        structural_lost = (
            bar.low <= signal.stop if signal.side is Side.LONG else bar.high >= signal.stop
        )
        if signal.side is Side.LONG:
            extreme = max(extreme, bar.high)
        else:
            extreme = min(extreme, bar.low)

        trail_lost = False
        if armed and len(session) >= atr_length + 1:
            atr = _atr_for_exit(session, atr_length)
            proposed = (
                extreme - trail_atr_multiple * atr
                if signal.side is Side.LONG else extreme + trail_atr_multiple * atr
            )
            trail = proposed if trail is None else (
                max(trail, proposed) if signal.side is Side.LONG else min(trail, proposed)
            )
            trail_lost = bar.close <= trail if signal.side is Side.LONG else bar.close >= trail

        joint_loss = False
        if len(session) >= ema_length:
            vwap = _vwap(session)
            ema = _ema([item.close for item in session], ema_length)
            joint_loss = (
                bar.close <= vwap and bar.close <= ema
                if signal.side is Side.LONG else bar.close >= vwap and bar.close >= ema
            )
        confirmed_loss = prior_joint_loss and joint_loss
        prior_joint_loss = joint_loss

        _set_first(plans, "structural_stop_90m", structural_lost, decision_time, "structural_stop", cap_reason)
        _set_first(plans, "confirmed_vwap_ema_90m", confirmed_loss, decision_time, "confirmed_vwap_ema_loss", cap_reason)
        _set_first(plans, "armed_chandelier_3atr_90m", trail_lost, decision_time, "armed_chandelier_3atr", cap_reason)
        hybrid_reason = (
            "structural_stop" if structural_lost else
            "confirmed_vwap_ema_loss" if confirmed_loss else
            "armed_chandelier_3atr" if trail_lost else None
        )
        _set_first(
            plans, "hybrid_armed_chandelier_vwap_ema_90m", hybrid_reason is not None,
            decision_time, hybrid_reason or "", cap_reason,
        )
        if not armed:
            armed = bar.close >= arm_price if signal.side is Side.LONG else bar.close <= arm_price
    return plans


def _set_first(
    plans: dict[str, PlannedExit], label: str, triggered: bool, decision_time: object,
    reason: str, cap_reason: str,
) -> None:
    if triggered and plans[label].reason == cap_reason:
        plans[label] = PlannedExit(label, decision_time, reason)
