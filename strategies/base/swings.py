"""
strategies/base/swings.py — _find_swings(): 2-bar pivot helper used ONLY
by dashboard chart overlays (not trading decisions).

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import pandas as pd


def _find_swings(df: pd.DataFrame, pivot_bars: int = 2) -> list[tuple[int, float, str]]:
    """
    2-bar lookback pivot detection — used ONLY by dashboard.py chart overlays
    for HH/LH/HL/LL visual labels. Trading decisions use MarketStructureAnalyzer
    (5-bar) instead. Keep these in sync if the cosmetic display ever changes.
    """
    pivots = []
    n = len(df)
    for i in range(pivot_bars, n - pivot_bars):
        hi = df.iloc[i]["high"]
        lo = df.iloc[i]["low"]
        left_bars  = df.iloc[i - pivot_bars : i]
        right_bars = df.iloc[i + 1 : i + pivot_bars + 1]
        if hi > left_bars["high"].max() and hi > right_bars["high"].max():
            pivots.append((i, float(hi), "high"))
        if lo < left_bars["low"].min() and lo < right_bars["low"].min():
            pivots.append((i, float(lo), "low"))
    return pivots
