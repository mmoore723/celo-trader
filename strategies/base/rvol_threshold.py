"""
strategies/base/rvol_threshold.py — Context-aware RVOL gate
(_get_dynamic_rvol_threshold) and its audit-log companion
(_rvol_threshold_reason).

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from signals import ORB_RVOL_THRESHOLD


def _get_dynamic_rvol_threshold(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> float:
    if msa_confirmed:
        # MSA confirmation means structure is validated — return the relaxed
        # threshold directly and bypass the early-session floor entirely.
        # Previously the floor of 1.0 silently overrode this 0.75, blocking
        # valid early-session entries even when structure was fully confirmed.
        return 0.75
    elif strategy_id == "CHAN_BREAK":
        threshold = 1.0
    else:
        mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
        if (mid_day
                and or_low is not None and close < or_low
                and vwap   is not None and close < vwap):
            threshold = 0.75
        else:
            threshold = ORB_RVOL_THRESHOLD

    # FIX 2026-07-28: mid_day's window starts at bar_min == 630 (10:30)
    # inclusive ("<="), but this floor used to check "> 630" (exclusive) —
    # at exactly 10:30 the mid-day relaxed threshold (0.75) would compute
    # correctly above, then get silently overridden back to 1.0 here since
    # the floor's strict comparison didn't consider 10:30 itself "past" the
    # boundary. Now uses ">=" to match mid_day's own boundary.
    floor = 0.75 if bar_min >= (10 * 60 + 30) else 1.0
    return max(threshold, floor)


def _rvol_threshold_reason(
    bar_min: int,
    close: float,
    or_low: "float | None",
    vwap: "float | None",
    strategy_id: str = "",
    msa_confirmed: bool = False,
) -> str:
    if msa_confirmed:
        return "structure confirmed (MSA) — relaxed to 0.75× (afternoon thinning expected)"
    if strategy_id == "CHAN_BREAK":
        return "CHAN_BREAK — 1.0× (channel touch needs real participation)"
    mid_day = (10 * 60 + 30) <= bar_min <= (13 * 60)
    if (mid_day and or_low is not None and close < or_low
            and vwap is not None and close < vwap):
        return "mid-day bleed (below OR Low + VWAP) — relaxed to 0.75×"
    return "default session threshold (ORB_RVOL_THRESHOLD)"
