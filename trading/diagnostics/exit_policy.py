"""Read-only descriptions of the policy actually selected by the manager."""
from __future__ import annotations

import pandas as pd

from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
from trading.v2_orb_paper_exit import V2_EXIT_MINUTES_BY_STRATEGY
from trading.vwap_displacement_exit import (
    FALLBACK_HOLD_MINUTES, VWAP_DISPLACEMENT_STRATEGY_ID,
)


def reviewed_exit_description(trade: dict, position: dict, now: object) -> str | None:
    """Narrate reviewed exits without evaluating, changing or placing an order.

    Return None for the existing generic manager. Use the same strategy
    classification and timer catalog as the actual exit dispatcher.
    """
    strategy = str(trade.get("strategy_id") or "").strip().upper()
    if not uses_v2_orb_execution_profile(strategy):
        return None
    pending = str(position.get("exit_pending_reason") or "").strip()
    if pending:
        return f"Exit requested: {pending}. Waiting for the broker to confirm the close."
    if strategy == VWAP_DISPLACEMENT_STRATEGY_ID:
        return (
            "Strategy exit: prior-high target or a completed 5-minute close below VWAP; "
            f"15:55 ET session cap. Missing structure has a {FALLBACK_HOLD_MINUTES}-minute "
            "fallback. Generic option stops and staged profit targets do not control this trade."
        )
    minutes = V2_EXIT_MINUTES_BY_STRATEGY.get(strategy)
    if minutes is None:
        return "Strategy exit policy unavailable in this display. No stop protection is confirmed here."
    raw_entry = position.get("entry_time") or trade.get("entry_time")
    try:
        entry, current = pd.Timestamp(raw_entry), pd.Timestamp(now)
        if pd.isna(entry) or pd.isna(current):
            raise ValueError("missing clock")
        entry = entry.tz_localize("America/New_York") if entry.tzinfo is None else entry
        current = current.tz_localize("America/New_York") if current.tzinfo is None else current
        elapsed = max(0.0, (current - entry).total_seconds() / 60)
        clock = (
            f"{elapsed:.1f}/{minutes} minutes held, {minutes - elapsed:.1f} minutes left."
            if elapsed < minutes else "Timer reached; close is due, not yet confirmed here."
        )
    except (TypeError, ValueError, OverflowError):
        clock = "Entry time unavailable; the manager must check its missing-time safety exit."
    return (
        f"Strategy exit: {minutes}-minute timer. {clock} "
        "Generic option stops, trails and staged profit targets do not control this trade. "
        "Account-level safety controls remain separate."
    )
