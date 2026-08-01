"""
trading/mtf_features/ema_stack.py — ema_stack_aligned(): checks whether the
EMA stack is aligned in the trade direction.

Split out of the old single trading/mtf_features.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import pandas as pd

# ── EMA-stack constants (used only by ema_stack_aligned below) ───────────────
_EMA_FAST = 8
_EMA_MID  = 21
_EMA_SLOW = 50


def ema_stack_aligned(df: pd.DataFrame, direction: str) -> bool:
    """
    True if the EMA stack is aligned in the trade direction.

    Bullish (CALL): EMA8 > EMA21 > EMA50 — all stacked up
    Bearish (PUT) : EMA8 < EMA21 < EMA50 — all stacked down

    Misalignment means the trend is breaking down and a VWAP breach is
    meaningful (used by the exit engine) or that momentum doesn't support
    a fresh entry yet (used by phase 2 decision support).
    """
    try:
        if len(df) < _EMA_SLOW + 5:
            return True   # insufficient data → assume aligned (don't block/exit prematurely)
        close = df["close"]
        ema8  = float(close.ewm(span=_EMA_FAST, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=_EMA_MID,  adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=_EMA_SLOW, adjust=False).mean().iloc[-1])
        if direction == "bullish":
            return ema8 > ema21 > ema50
        else:
            return ema8 < ema21 < ema50
    except Exception:
        return True
