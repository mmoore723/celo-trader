"""
trading/position_manager/indicators.py — ATR/VWAP/swing math specific to the
position-management trailing stop (not the shared MTF indicators, which
live in trading/mtf_features.py).

Split out of trading/position_manager.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from trading.position_manager.constants import _SWING_LOOKBACK, _DELTA_APPROX


def _compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """14-bar ATR on 1-min underlying bars."""
    try:
        if len(df) < period + 1:
            return None
        hl  = df["high"]  - df["low"]
        hpc = (df["high"]  - df["close"].shift(1)).abs()
        lpc = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        atr = float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
        return atr if atr > 0 else None
    except Exception:
        return None


def _compute_vwap(df: pd.DataFrame) -> Optional[float]:
    """Session VWAP from 1-min bars (cumulative typical price x volume)."""
    try:
        if df.empty:
            return None
        tp  = (df["high"] + df["low"] + df["close"]) / 3.0
        cum_tpv = (tp * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        vwap_series = cum_tpv / cum_vol.replace(0, np.nan)
        val = float(vwap_series.iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def _structural_swing_stop(df: pd.DataFrame, direction: str, lookback: int = _SWING_LOOKBACK) -> Optional[float]:
    """
    Most recent confirmed swing low (for calls) or swing high (for puts) on
    the underlying, looked back `lookback` bars. 3-bar pivot: a bar whose
    low < both neighbors (or high > both neighbors).
    """
    try:
        if len(df) < lookback + 2:
            return None
        window = df.iloc[-lookback:].reset_index(drop=True)
        pivots = []
        for i in range(1, len(window) - 1):
            if direction == "bullish":
                if window.iloc[i]["low"] < window.iloc[i-1]["low"] and \
                   window.iloc[i]["low"] < window.iloc[i+1]["low"]:
                    pivots.append(float(window.iloc[i]["low"]))
            else:
                if window.iloc[i]["high"] > window.iloc[i-1]["high"] and \
                   window.iloc[i]["high"] > window.iloc[i+1]["high"]:
                    pivots.append(float(window.iloc[i]["high"]))
        return pivots[-1] if pivots else None
    except Exception:
        return None


def _underlying_stop_to_option(
    entry_option: float,
    underlying_current: float,
    underlying_stop: float,
) -> float:
    """
    Convert an underlying stop level to an option stop price using delta.
    Option stop = entry_option - |move| * DELTA_APPROX, floored at 20%
    below entry (hard safety net).
    """
    move         = abs(underlying_current - underlying_stop)
    option_stop  = entry_option - move * _DELTA_APPROX
    hard_floor   = entry_option * 0.80
    return round(max(option_stop, hard_floor, 0.01), 4)
