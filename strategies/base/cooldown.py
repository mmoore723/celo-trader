"""
strategies/base/cooldown.py — Per-strategy/per-ticker signal cooldown
tracker.

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

IMPORTANT: `_signal_cooldown` is mutated IN PLACE (never reassigned) by
check_cooldown/register_cooldown below, and separately by
backtester/simulate.py, which does `from strategies.base import
_signal_cooldown` then calls `_signal_cooldown.clear()` between backtest
runs. Both this module's own functions and the package's __init__.py
re-export must keep referring to the SAME dict object — re-exporting via
`from strategies.base.cooldown import _signal_cooldown` (a plain reference,
not a copy) preserves that identity, same pattern already verified for
strategies/inst_orb's _retest_state/_recent_expirations earlier this
session.
"""

from __future__ import annotations

import pandas as pd

# Keys: (strategy_id, ticker, date_str)  →  last-fired pd.Timestamp
# Date component ensures the cooldown resets automatically at midnight without
# any explicit flush — the bot runs 24/7 via systemd, so without a date key
# a signal fired at 14:30 on Monday would still block 09:45 on Tuesday.
_signal_cooldown: dict[tuple[str, str, str], pd.Timestamp] = {}
SIGNAL_COOLDOWN_MINUTES: int = 20


def _cooldown_key(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> tuple:
    """Key is (strategy, ticker, date) so cooldown auto-resets each trading day."""
    date_str = bar_time.strftime("%Y-%m-%d") if hasattr(bar_time, "strftime") else str(bar_time)[:10]
    return (strategy_id, ticker, date_str)


def check_cooldown(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> bool:
    """
    Return True if the strategy is BLOCKED by cooldown (fired too recently).
    Call before heavy gate evaluation to short-circuit fast.
    """
    key = _cooldown_key(strategy_id, ticker, bar_time)
    last = _signal_cooldown.get(key)
    if last is None:
        return False
    minutes_since = (bar_time - last).total_seconds() / 60
    return minutes_since < SIGNAL_COOLDOWN_MINUTES


def register_cooldown(strategy_id: str, ticker: str, bar_time: pd.Timestamp) -> None:
    """Record that this strategy just fired. Call immediately before returning a Signal."""
    key = _cooldown_key(strategy_id, ticker, bar_time)
    _signal_cooldown[key] = bar_time
