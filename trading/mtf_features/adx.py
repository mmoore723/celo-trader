"""
trading/mtf_features/adx.py — compute_adx(): Wilder's ADX on 1-min bars.

Split out of the old single trading/mtf_features.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("celo_trader.trading.mtf_features")


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Wilder's ADX on 1-min bars.
    ADX < 20 = no directional trend (choppy / ranging).
    """
    try:
        if len(df) < period * 2:
            return None
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)
        close = df["close"].values.astype(float)

        # True Range
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )

        # Directional movement
        plus_dm  = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                             np.maximum(high[1:] - high[:-1], 0), 0)
        minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                             np.maximum(low[:-1] - low[1:], 0), 0)

        # Wilder smoothing (EMA with alpha = 1/period)
        def wilder_smooth(arr, n):
            out = np.zeros(len(arr))
            out[0] = arr[:n].sum()
            for i in range(1, len(arr)):
                out[i] = out[i-1] - out[i-1] / n + arr[i]
            return out

        atr_w  = wilder_smooth(tr, period)
        pdm_w  = wilder_smooth(plus_dm, period)
        mdm_w  = wilder_smooth(minus_dm, period)

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi    = np.where(atr_w > 0, 100 * pdm_w / atr_w, 0)
            mdi    = np.where(atr_w > 0, 100 * mdm_w / atr_w, 0)
            dx_den = pdi + mdi
            dx     = np.where(dx_den > 0, 100 * np.abs(pdi - mdi) / dx_den, 0)

        adx_w  = wilder_smooth(dx[period:], period)
        # FIX 2026-07-28: wilder_smooth() returns a smoothed SUM, not an
        # average — fine for atr_w/pdm_w/mdm_w above since they're only ever
        # used as a ratio (pdi/mdi), where the shared scale-up cancels out.
        # But adx_w was being returned directly with no such ratio, so it
        # stayed inflated by a factor of `period` (proven algebraically:
        # sum[i] = period * avg[i] holds at every step of the recursion, not
        # just asymptotically — confirmed against a synthetic DX series
        # before applying this). Live evidence: the AI decision-support layer
        # once vetoed a real signal after receiving an impossible ADX of 676.94
        # — 676.94/14≈48, a plausible real value. This also silently weakened
        # position_manager.py's ADX<20 exit condition on every open position
        # (inflated ADX rarely reads below 20) and fed the same bad number
        # into historical exit simulations.
        return float(adx_w[-1]) / period if len(adx_w) > 0 else None
    except Exception as ex:
        logger.debug("ADX computation failed: %s", ex)
        return None
