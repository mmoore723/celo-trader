"""
strategies/vwap_pb/pullback.py — _count_prior_pullbacks(): counts how many
times price has already touched VWAP during the current trend leg.

Split out of the old single strategies/vwap_pb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. Fully self-contained (all inputs
passed as parameters, no module-global reads) except for the lookback bound,
which is now an explicit parameter (`lookback`) instead of a bare read of the
module-level `_PULLBACK_LOOKBACK` global — the caller (evaluate.py) passes
the live value it already fetched from the package namespace, so this
function stays a pure, easily-testable helper. The default of 60 matches the
original `_PULLBACK_LOOKBACK = 60` constant exactly, so any other caller
that omits the argument gets identical behavior to the original.
"""

from __future__ import annotations

import pandas as pd


def _count_prior_pullbacks(
    today: pd.DataFrame,
    direction: str,
    touch_pct: float,
    lookback: int = 60,
) -> int:
    """Walk backward from the current bar counting distinct VWAP-touch runs,
    stopping at the trend leg's boundary (EMA50 crossing VWAP) or after
    `lookback` bars, whichever comes first."""
    n = len(today)
    if n < 4:
        return 0
    end = max(0, n - 2 - lookback)
    count = 0
    in_touch_run = False
    for i in range(n - 3, end - 1, -1):
        bar   = today.iloc[i]
        vwap  = float(bar.get("vwap", float("nan")))
        ema50 = float(bar.get("ema50", float("nan")))
        if pd.isna(vwap) or pd.isna(ema50):
            break
        if direction == "bullish" and ema50 <= vwap:
            break
        if direction == "bearish" and ema50 >= vwap:
            break
        low, high = float(bar["low"]), float(bar["high"])
        is_touch = (
            (direction == "bullish" and low  <= vwap and low  >= vwap * (1.0 - touch_pct))
            or (direction == "bearish" and high >= vwap and high <= vwap * (1.0 + touch_pct))
        )
        if is_touch:
            if not in_touch_run:
                count += 1
                in_touch_run = True
        else:
            in_touch_run = False
    return count
