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
    # One-open-SPY-position paid study selected 30 minutes earlier and passed
    # 66 untouched later trades. The 90-minute per-signal diagnostic allowed
    # overlapping SPY positions, so it is not the executable account policy.
    "V2_SPY_TREND_CONT": 30,
    "V2_SPY_AFTERNOON_FVG": 30,
    "V2_SPY_AFTERNOON_REVERSAL": 30,
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": 90,
}
V2_PRE_CLOSE_EXIT_STRATEGY_IDS = frozenset({"V2_TSLA_NOISE_MOMENTUM"})


def evaluate_v2_orb_paper_exit(
    entry_time: datetime | None,
    now: datetime,
    strategy_id: object = "V2_ORB_PULLBACK",
) -> tuple[bool, str]:
    """Return the exact research markout timing, with a safe bad-state exit."""
    if entry_time is None:
        return True, "v2_orb_missing_entry_time_safety"
    normalized_strategy_id = str(strategy_id or "").strip().upper()
    if normalized_strategy_id in V2_PRE_CLOSE_EXIT_STRATEGY_IDS:
        # The paid TSLA study did not select a duration. It selected the
        # same-session 15:59 ET option bid, so preserve that actual rule.
        cutoff = entry_time.replace(hour=15, minute=59, second=0, microsecond=0)
        if now >= cutoff:
            elapsed_minutes = (now - entry_time).total_seconds() / 60
            return True, f"v2_tsla_noise_paid_markout_preclose_1559 (held={elapsed_minutes:.1f}min)"
        return False, "hold"
    hold_minutes = V2_EXIT_MINUTES_BY_STRATEGY.get(
        normalized_strategy_id, V2_ORB_PAID_MARKOUT_MINUTES,
    )
    elapsed_minutes = (now - entry_time).total_seconds() / 60
    if elapsed_minutes >= hold_minutes:
        prefix = {
            "V2_TREND_CONT": "v2_trend",
            "V2_SPY_TREND_CONT": "v2_spy_trend",
            "V2_SPY_AFTERNOON_FVG": "v2_spy_afternoon_fvg",
            "V2_SPY_AFTERNOON_REVERSAL": "v2_spy_afternoon_reversal",
            "V2_TSLA_TWO_LEG_TREND_PULLBACK": "v2_tsla_two_leg_trend_pullback",
        }.get(normalized_strategy_id, "v2_orb")
        return True, (
            f"{prefix}_paid_markout_{hold_minutes}m "
            f"(held={elapsed_minutes:.1f}min)"
        )
    return False, "hold"
