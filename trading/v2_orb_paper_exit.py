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


def evaluate_v2_orb_paper_exit(
    entry_time: datetime | None,
    now: datetime,
) -> tuple[bool, str]:
    """Return the exact research markout timing, with a safe bad-state exit."""
    if entry_time is None:
        return True, "v2_orb_missing_entry_time_safety"
    elapsed_minutes = (now - entry_time).total_seconds() / 60
    if elapsed_minutes >= V2_ORB_PAID_MARKOUT_MINUTES:
        return True, (
            f"v2_orb_paid_markout_{V2_ORB_PAID_MARKOUT_MINUTES}m "
            f"(held={elapsed_minutes:.1f}min)"
        )
    return False, "hold"
