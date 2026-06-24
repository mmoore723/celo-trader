"""
strategies/aft_rev.py — Afternoon Reversal (AFT_REV)

Session: 13:00–15:30 ET | Direction: bullish

After a mid-day sell-off, fires when structure shows the first confirmed
Higher Low followed by a break above the most recent Swing High.

Gates:
  1. Session: 13:00–15:30 ET
  2. RVOL ≥ 1.0 (afternoon is quieter but still needs real participation)
  3. Volume > vol_sma20 × 1.2
  4. MSA confirmed Higher Low
  5. Price closes above the most recent Swing High (BOS bullish)
  Bonus: VWAP alignment adds to confidence (soft gate)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer

logger = logging.getLogger("celo_trader.strategies.aft_rev")

STRATEGY_ID = "AFT_REV"


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 12:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window 13:00–15:30
    if not (13 * 60 <= bar_min <= 15 * 60 + 30):
        return None

    close   = float(last_bar["close"])
    vwap    = float(last_bar["vwap"])      if not pd.isna(last_bar.get("vwap",     np.nan)) else None
    rvol    = float(last_bar["rvol"])      if not pd.isna(last_bar.get("rvol",     np.nan)) else 0.0
    vol     = float(last_bar["volume"])
    vol_sma = float(last_bar["vol_sma20"]) if not pd.isna(last_bar.get("vol_sma20", np.nan)) else 0.0

    # Gate 2: RVOL floor
    if rvol < 1.0:
        logger.debug("[%s] AFT_REV: RVOL %.2f < 1.0 — no institutional participation", ticker, rvol)
        return None

    # Gate 3: volume vs SMA
    if vol_sma > 0 and vol < vol_sma * 1.2:
        logger.debug("[%s] AFT_REV: vol %.0f < sma×1.2 (%.0f) — skipped", ticker, vol, vol_sma * 1.2)
        return None

    msa = MarketStructureAnalyzer(today)

    # Gate 4: confirmed Higher Low
    if not msa.confirmed_higher_low():
        logger.debug("[%s] AFT_REV: no confirmed HL — skipped", ticker)
        return None

    # Gate 5: close above most recent Swing High (BOS)
    prev_sh = msa.last_swing_high()
    if prev_sh is None:
        logger.debug("[%s] AFT_REV: no swing high detected — skipped", ticker)
        return None
    if close <= prev_sh:
        logger.debug("[%s] AFT_REV: close %.2f <= last SH %.2f — no BOS yet", ticker, close, prev_sh)
        return None

    vwap_bonus   = 0.05 if (vwap is not None and close > vwap) else 0.0
    breakout_mag = (close - prev_sh) / prev_sh
    mag_bonus    = min(0.04, breakout_mag * 10)
    trend        = msa.classify_trend()
    trend_bonus  = 0.03 if trend == "consolidation" else (0.01 if trend == "uptrend" else 0.0)

    confidence = min(0.84, 0.62 + min(rvol - 1.0, 2.0) * 0.05 + vwap_bonus + mag_bonus + trend_bonus)

    logger.info("[%s] AFT_REV bullish close=%.2f prev_sh=%.2f RVOL=%.2f trend=%s conf=%.2f",
                ticker, close, prev_sh, rvol, trend, confidence)
    return Signal(
        strategy_id = STRATEGY_ID,
        direction   = "bullish",
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "prev_swing_high": prev_sh,
            "hl_confirmed":    True,
            "trend":           trend,
            "vwap":            vwap,
            "breakout_pct":    round(breakout_mag * 100, 2),
        },
    )
