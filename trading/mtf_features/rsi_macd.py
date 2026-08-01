"""
trading/mtf_features/rsi_macd.py — compute_rsi(), compute_macd_hist().

Split out of the old single trading/mtf_features.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """RSI on the most recent bar. Returns None if insufficient history."""
    try:
        if len(df) < period + 2:
            return None
        close = df["close"].astype(float)
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, np.nan)
        rsi   = 100.0 - (100.0 / (1.0 + rs))
        val   = float(rsi.iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def compute_macd_hist(df: pd.DataFrame,
                       fast: int = 12, slow: int = 26, sig: int = 9) -> list:
    """Returns last 3 MACD histogram values (most recent last). Empty list if not enough data."""
    try:
        if len(df) < slow + sig:
            return []
        close     = df["close"].astype(float)
        ema_fast  = close.ewm(span=fast, adjust=False).mean()
        ema_slow  = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        sig_line  = macd_line.ewm(span=sig, adjust=False).mean()
        hist      = (macd_line - sig_line).tolist()
        return hist[-3:]
    except Exception:
        return []
