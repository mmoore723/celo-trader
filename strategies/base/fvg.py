"""
strategies/base/fvg.py — _has_recent_fvg(): Fair Value Gap scanner helper
used by BOS_MSS.

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import pandas as pd


def _has_recent_fvg(today: pd.DataFrame, direction: str, lookback: int = 20) -> bool:
    """
    Return True if a confirmed Fair Value Gap of the given direction exists
    within the last `lookback` bars. Used by BOS_MSS to require imbalance
    evidence before firing a market-structure-shift signal.
    """
    n = len(today)
    if n < 3:
        return False
    window = min(lookback, n - 2)
    for k in range(n - 2, max(n - 2 - window, 1), -1):
        if k - 1 < 0:
            break
        b_prev = today.iloc[k - 1]
        b_next = today.iloc[k + 1]
        if direction == "bullish":
            if float(b_prev["low"]) > float(b_next["high"]):
                return True
        else:
            if float(b_prev["high"]) < float(b_next["low"]):
                return True
    return False
