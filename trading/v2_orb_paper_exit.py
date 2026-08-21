"""Exit rule for the TSLA-only V2 ORB paper-validation pilot.

The paid historical study measured one precise hypothesis: enter at the
observed ask, then exit the same contract at its observed bid 90 minutes
later.  Applying the platform's generic chandelier or 75-minute exits to
that paper pilot would test a different hypothesis and make the comparison
misleading.

This module is deliberately narrow.  It is called only for a paper trade
whose stored strategy ID is ``V2_ORB_PULLBACK``.  Live positions, global
maintenance/kill controls, and every other strategy retain their usual exit
paths.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from config.strategy_catalog import REVIEWED_STRATEGIES


V2_ORB_PAID_MARKOUT_MINUTES = 90
V2_EXIT_MINUTES_BY_STRATEGY = {
    strategy_id: rule.exit_minutes
    for strategy_id, rule in REVIEWED_STRATEGIES.items()
    if rule.exit_minutes is not None
}


def reviewed_entry_fits_session(
    now: datetime,
    strategy_id: object,
    *,
    cutoff: time = time(15, 55),
) -> tuple[bool, str]:
    """Return whether a reviewed fixed-hold entry can exit before cutoff."""
    normalized = str(strategy_id or "").strip().upper()
    hold_minutes = V2_EXIT_MINUTES_BY_STRATEGY.get(normalized)
    if hold_minutes is None:
        return True, "not_fixed_hold"
    cutoff_at = now.replace(
        hour=cutoff.hour, minute=cutoff.minute, second=0, microsecond=0,
    )
    if now + timedelta(minutes=hold_minutes) > cutoff_at:
        latest_entry = cutoff_at - timedelta(minutes=hold_minutes)
        return False, (
            f"reviewed_hold_would_cross_cutoff "
            f"(hold={hold_minutes}m latest_entry={latest_entry:%H:%M} ET)"
        )
    return True, "fits_session"


def evaluate_v2_orb_paper_exit(
    entry_time: datetime | None,
    now: datetime,
    strategy_id: object = "V2_ORB_PULLBACK",
) -> tuple[bool, str]:
    """Return the exact research markout timing, with a safe bad-state exit."""
    if entry_time is None:
        return True, "v2_orb_missing_entry_time_safety"
    normalized_strategy_id = str(strategy_id or "").strip().upper()
    hold_minutes = V2_EXIT_MINUTES_BY_STRATEGY.get(
        normalized_strategy_id, V2_ORB_PAID_MARKOUT_MINUTES,
    )
    elapsed_minutes = (now - entry_time).total_seconds() / 60
    if elapsed_minutes >= hold_minutes:
        prefix = {
            "V2_SPY_TREND_CONT": "v2_spy_trend",
            "V2_SPY_AFTERNOON_FVG": "v2_spy_afternoon_fvg",
            "V2_FAILED_OR_BREAK_VWAP_REVERSION": "v2_spy_failed_range_recovery",
            "V2_TSLA_TWO_LEG_TREND_PULLBACK": "v2_tsla_two_leg_trend_pullback",
        }.get(normalized_strategy_id, "v2_orb")
        return True, (
            f"{prefix}_paid_markout_{hold_minutes}m "
            f"(held={elapsed_minutes:.1f}min)"
        )
    return False, "hold"
