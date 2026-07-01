"""
strategies/aft_rev.py — Afternoon Reversal (AFT_REV)

Session: 13:00–15:30 ET | Direction: BOTH (bullish + bearish)

After a sustained morning move, fires when structure shows the first confirmed
reversal pivot followed by a break through the most recent swing level.

  Bullish: confirmed Higher Low + break above most recent Swing High
           (afternoon recovery after mid-day sell-off)
  Bearish: confirmed Lower High + break below most recent Swing Low
           (afternoon distribution after morning rally — mirror pattern)

Gates:
  1. Session: 13:00–15:30 ET
  2. RVOL ≥ 1.0 (afternoon is quieter but still needs real participation)
  3. [Gate 3 REMOVED] — intraday vol_sma inflated by opening spike bar
  4. MSA confirmed Higher Low (bullish) or Lower High (bearish)
  5. Price closes above most recent Swing High (bullish BOS)
       or below most recent Swing Low (bearish BOS)
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

    # Gate 2: RVOL floor
    if rvol < 1.0:
        logger.debug("[%s] AFT_REV: RVOL %.2f < 1.0 — no institutional participation", ticker, rvol)
        return None

    # Gate 3: REMOVED — intraday vol_sma inflated by opening spike bar (same issue
    # as MID_BRK Gate 5). RVOL gate (Gate 2) already handles participation using
    # a proper 10-day baseline. Redundant vol_sma check was blocking valid afternoon
    # reversal setups when session opened with high volume.

    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()

    # ── BULLISH path: confirmed HL + break above most recent Swing High ────────
    # Classic afternoon recovery: mid-day sell-off found a Higher Low (sellers
    # exhausted), then price breaks the prior Swing High = bullish BOS. Institutions
    # are re-entering. VWAP reclaim above confirms bullish flow.
    if msa.confirmed_higher_low():
        prev_sh = msa.last_swing_high()
        if prev_sh is not None and close > prev_sh:
            vwap_bonus   = 0.05 if (vwap is not None and close > vwap) else 0.0
            breakout_mag = (close - prev_sh) / max(prev_sh, 1.0)
            mag_bonus    = min(0.04, breakout_mag * 10)
            trend_bonus  = 0.03 if trend == "consolidation" else (0.01 if trend == "uptrend" else 0.0)
            confidence   = min(0.84, 0.62 + min(rvol - 1.0, 2.0) * 0.05 + vwap_bonus + mag_bonus + trend_bonus)

            logger.info("[%s] AFT_REV bullish close=%.2f prev_sh=%.2f RVOL=%.2f trend=%s conf=%.2f",
                        ticker, close, prev_sh, rvol, trend, confidence)
            return Signal(
                strategy_id = STRATEGY_ID,
                direction   = "bullish",
                confidence  = confidence,
                rvol        = rvol,
                trigger_bar = bar_time,
                meta        = {
                    "trigger":         "hl_bos_bullish",
                    "prev_swing_high": prev_sh,
                    "hl_confirmed":    True,
                    "trend":           trend,
                    "vwap":            vwap,
                    "breakout_pct":    round(breakout_mag * 100, 2),
                },
            )
        else:
            if prev_sh is None:
                logger.debug("[%s] AFT_REV bullish: no swing high detected — skipped", ticker)
            else:
                logger.debug("[%s] AFT_REV bullish: close %.2f <= last SH %.2f — no BOS yet", ticker, close, prev_sh)

    # ── BEARISH path: confirmed LH + break below most recent Swing Low ─────────
    # Mirror pattern: morning rally topped out with a Lower High (buyers exhausted),
    # then price breaks the prior Swing Low = bearish BOS. Distribution underway.
    # VWAP rejection below confirms bearish flow — institutions selling into strength.
    if msa.confirmed_lower_high():
        prev_sl = msa.last_swing_low()
        if prev_sl is not None and close < prev_sl:
            vwap_bonus   = 0.05 if (vwap is not None and close < vwap) else 0.0
            breakdown_mag = (prev_sl - close) / max(prev_sl, 1.0)
            mag_bonus     = min(0.04, breakdown_mag * 10)
            trend_bonus   = 0.03 if trend == "consolidation" else (0.01 if trend == "downtrend" else 0.0)
            confidence    = min(0.84, 0.62 + min(rvol - 1.0, 2.0) * 0.05 + vwap_bonus + mag_bonus + trend_bonus)

            logger.info("[%s] AFT_REV bearish close=%.2f prev_sl=%.2f RVOL=%.2f trend=%s conf=%.2f",
                        ticker, close, prev_sl, rvol, trend, confidence)
            return Signal(
                strategy_id = STRATEGY_ID,
                direction   = "bearish",
                confidence  = confidence,
                rvol        = rvol,
                trigger_bar = bar_time,
                meta        = {
                    "trigger":        "lh_bos_bearish",
                    "prev_swing_low": prev_sl,
                    "lh_confirmed":   True,
                    "trend":          trend,
                    "vwap":           vwap,
                    "breakdown_pct":  round(breakdown_mag * 100, 2),
                },
            )
        else:
            if prev_sl is None:
                logger.debug("[%s] AFT_REV bearish: no swing low detected — skipped", ticker)
            else:
                logger.debug("[%s] AFT_REV bearish: close %.2f >= last SL %.2f — no BOS yet", ticker, close, prev_sl)

    return None
