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

from datetime import datetime


V2_ORB_PAID_MARKOUT_MINUTES = 90
V2_EXIT_MINUTES_BY_STRATEGY = {
    "V2_ORB_PULLBACK": 90,
    # Preserved legacy research identity.  It remains separately gated and
    # is not the reviewed SPY rule below.
    "V2_TREND_CONT": 90,
    "V2_SPY_TREND_CONT": 30,
}


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
            "V2_TREND_CONT": "v2_trend",
            "V2_SPY_TREND_CONT": "v2_spy_trend",
        }.get(normalized_strategy_id, "v2_orb")
        return True, (
            f"{prefix}_paid_markout_{hold_minutes}m "
            f"(held={elapsed_minutes:.1f}min)"
        )
    return False, "hold"
