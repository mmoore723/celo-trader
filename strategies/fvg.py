"""
strategies/fvg.py — Fair Value Gap (FVG)

Three-candle imbalance retest. Entry fires when the current bar closes INTO
the gap on the correct side.

Gates:
  1. Gap width ≥ 0.5× ATR14
  2. RVOL ≥ 1.5× on the retest bar
  3. VWAP alignment
  4. Session ≥ 09:45 ET (pre-structure gaps are noise)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal

logger = logging.getLogger("celo_trader.strategies.fvg")

STRATEGY_ID = "FVG"


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 6:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    if bar_min < 9 * 60 + 45:
        return None

    c_close = float(last_bar["close"])
    c_vwap  = float(last_bar["vwap"]) if not pd.isna(last_bar.get("vwap", np.nan)) else None
    c_rvol  = float(last_bar["rvol"]) if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0
    atr     = float(last_bar["atr"])  if not pd.isna(last_bar.get("atr",  np.nan)) else 0.0

    look_back = min(20, len(today) - 2)

    for k in range(look_back, 0, -1):
        if k - 1 < 0 or k + 1 >= len(today):
            continue

        b_prev   = today.iloc[k - 1]
        b_middle = today.iloc[k]
        b_next   = today.iloc[k + 1]

        gap_low  = None
        gap_high = None
        direction = None

        if float(b_prev["low"]) > float(b_next["high"]):
            gap_low   = float(b_next["high"])
            gap_high  = float(b_prev["low"])
            direction = "bullish"
        elif float(b_prev["high"]) < float(b_next["low"]):
            gap_low   = float(b_prev["high"])
            gap_high  = float(b_next["low"])
            direction = "bearish"

        if direction is None:
            continue

        gap_width = gap_high - gap_low
        if atr > 0 and gap_width < 0.5 * atr:
            continue

        if not (gap_low <= c_close <= gap_high):
            continue

        if c_rvol < 1.5:
            logger.debug("[%s] FVG %s: RVOL %.2f < 1.5 — skipped", ticker, direction, c_rvol)
            continue

        if c_vwap is not None:
            if direction == "bullish" and c_close < c_vwap:
                continue
            if direction == "bearish" and c_close > c_vwap:
                continue

        gap_ratio  = gap_width / atr if atr > 0 else 1.0
        confidence = min(0.80, 0.55 + min(gap_ratio, 2.0) * 0.10 + min(c_rvol - 1.5, 1.0) * 0.05)

        logger.info("[%s] FVG %s signal gap=[%.4f–%.4f] RVOL=%.2f conf=%.2f",
                    ticker, direction, gap_low, gap_high, c_rvol, confidence)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = direction,
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "gap_low":    gap_low,
                "gap_high":   gap_high,
                "gap_width":  gap_width,
                "atr":        atr,
                "vwap":       c_vwap,
                "formed_bar": b_middle["time"],
            },
        )

    return None
