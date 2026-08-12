"""Retired completed-five-minute V2 ORB adapter.

The V2 ORB now uses a fifteen-minute opening range and a one-minute
close-confirmed breakout followed by a live first retouch.  That cannot be
represented by an evaluator which sees completed OHLCV candles only, so its
order-facing signal is injected by ``trading.orb_retouch_execution`` into the
normal router.  Keeping this module as a no-op prevents the former delayed
five-minute pullback from being emitted in parallel.
"""
from __future__ import annotations

import pandas as pd
from strategies.base import Signal

STRATEGY_ID = "V2_ORB_PULLBACK"
# Chosen once on the earlier paid TSLA option data, then positive on the
# untouched later segment (see paid_tsla_orb_entry_rules.json).  Keep this
# explicit so the paper cohort does not silently revert to the research
# baseline's wider 0.10% allowance.
PAID_RETEST_TOLERANCE_PCT = 0.0005
# This hypothesis was tested only on paid TSLA option quotes.  Keep the scope
# in the strategy adapter—not merely in a screen or router setting—so a future
# pilot cannot accidentally trade an unvalidated ticker.
VALIDATED_TICKERS = frozenset({"TSLA"})


def evaluate(today: pd.DataFrame, ticker: str = "") -> Signal | None:
    # See the module docstring.  Do not restore the old delayed-candle path
    # merely because this function is still listed in ACTIVE_STRATEGIES.
    return None
