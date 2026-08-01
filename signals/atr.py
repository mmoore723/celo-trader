"""
signals/atr.py — compute_atr(): Average True Range.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) over `period` bars.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    Used by the chart API to surface volatility context.
    """
    if df.empty or len(df) < 2:
        return pd.Series([np.nan] * len(df), index=df.index, name="atr")
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().rename("atr")
