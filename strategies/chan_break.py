"""
strategies/chan_break.py — Channel Trendline Rejection (CHAN_BREAK)

Session: 09:45–14:00 ET | Direction: both

Short at descending channel upper trendline, long at ascending channel lower
trendline. Requires a touch within 0.3% of the projected level + a close-past-
the-line rejection/bounce candle + RVOL.

Detection (descending channel — bearish):
  1. Find 2 most recent MSA swing highs where SH2 < SH1
  2. Project trendline to current bar
  3. Bar HIGH tags within 0.3% of the projected level
  4. Bar CLOSE is below the projected level (rejection)
  5. VWAP alignment (close < VWAP for bearish)
  6. RVOL ≥ dynamic threshold (msa_confirmed=True → 0.75× floor)

Mirror logic for ascending channel (bullish).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import (
    Signal,
    MarketStructureAnalyzer,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
)

logger = logging.getLogger("celo_trader.strategies.chan_break")

STRATEGY_ID = "CHAN_BREAK"

_MIN_SLOPE   = 0.002   # per-bar slope below this = flat channel = noise
_MAX_AGE     = 40      # bars; older pivots = stale channel
_TOUCH_TOL   = 0.003   # 0.3% touch tolerance


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 25:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window 09:45–14:00
    if not (9 * 60 + 45 <= bar_min <= 14 * 60):
        return None

    rvol     = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    vwap     = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    close    = float(last_bar["close"])
    high     = float(last_bar["high"])
    low_     = float(last_bar["low"])
    curr_idx = len(today) - 1

    # Compute dynamic RVOL threshold — structure-confirmed since a verified
    # channel (descending SH pair) IS MSA confirmation.
    rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, None, vwap, STRATEGY_ID, msa_confirmed=True)

    msa   = MarketStructureAnalyzer(today)
    highs = msa._highs()
    lows  = msa._lows()

    # ── DESCENDING CHANNEL: bearish short ────────────────────────────────────
    if len(highs) >= 2:
        for j in range(len(highs) - 1, 0, -1):
            sh2 = highs[j]       # more recent, lower
            sh1 = highs[j - 1]   # older, higher

            if sh2["price"] >= sh1["price"]:
                continue

            if (curr_idx - sh1["idx"]) > _MAX_AGE:
                break

            slope = (sh2["price"] - sh1["price"]) / max(sh2["idx"] - sh1["idx"], 1)
            if abs(slope) < _MIN_SLOPE:
                logger.debug("[%s] CHAN_BREAK: slope %.4f too flat", ticker, slope)
                continue

            projected = sh2["price"] + slope * (curr_idx - sh2["idx"])
            touch_pct = (high - projected) / max(projected, 1.0)

            if not (-0.001 <= touch_pct <= _TOUCH_TOL):
                logger.debug("[%s] CHAN_BREAK bearish: high %.2f vs projected %.2f (touch %.3f%%) — no tag",
                             ticker, high, projected, touch_pct * 100)
                break

            if close >= projected:
                logger.debug("[%s] CHAN_BREAK bearish: close %.2f >= projected %.2f — no rejection",
                             ticker, close, projected)
                break

            if vwap is not None and close >= vwap:
                logger.debug("[%s] CHAN_BREAK bearish: close %.2f >= vwap %.2f", ticker, close, vwap)
                break

            if rvol < rvol_min:
                logger.debug("[%s] CHAN_BREAK bearish: RVOL %.2f < %.2f — skipped", ticker, rvol, rvol_min)
                break

            rejection_body = (high - close) / max(high - low_, 0.01)
            channel_age    = curr_idx - sh1["idx"]
            recency_bonus  = max(0, 0.05 - channel_age * 0.001)
            rvol_bonus     = min(0.08, max(rvol - rvol_min, 0) * 0.07)
            body_bonus     = min(0.05, rejection_body * 0.06)
            confidence     = min(0.90, 0.75 + rvol_bonus + body_bonus + recency_bonus)

            logger.info(
                "[%s] CHAN_BREAK bearish rejection: sh1=%.2f sh2=%.2f slope=%.4f "
                "projected=%.2f high=%.2f close=%.2f RVOL=%.2f (min=%.2f) conf=%.2f",
                ticker, sh1["price"], sh2["price"], slope,
                projected, high, close, rvol, rvol_min, confidence,
            )
            return Signal(
                strategy_id = STRATEGY_ID,
                direction   = "bearish",
                trigger_bar = bar_time,
                confidence  = confidence,
                rvol        = rvol,
                meta        = {
                    "trigger":          "descending_channel_rejection",
                    "sh1_price":        sh1["price"],
                    "sh2_price":        sh2["price"],
                    "slope_per_bar":    round(slope, 4),
                    "projected":        round(projected, 2),
                    "touch_pct":        round(touch_pct * 100, 3),
                    "rejection_body":   round(rejection_body, 2),
                    "entry_bar_high":   round(high, 4),
                    "rvol_gate":        round(rvol_min, 2),
                    "rvol_gate_reason": _rvol_threshold_reason(
                        bar_min, close, None, vwap, STRATEGY_ID, msa_confirmed=True),
                },
            )

    # ── ASCENDING CHANNEL: bullish long ──────────────────────────────────────
    if len(lows) >= 2:
        for j in range(len(lows) - 1, 0, -1):
            sl2 = lows[j]        # more recent, higher
            sl1 = lows[j - 1]    # older, lower

            if sl2["price"] <= sl1["price"]:
                continue

            if (curr_idx - sl1["idx"]) > _MAX_AGE:
                break

            slope = (sl2["price"] - sl1["price"]) / max(sl2["idx"] - sl1["idx"], 1)
            if abs(slope) < _MIN_SLOPE:
                logger.debug("[%s] CHAN_BREAK ascending: slope %.4f too flat", ticker, slope)
                continue

            projected = sl2["price"] + slope * (curr_idx - sl2["idx"])
            touch_pct = (projected - low_) / max(projected, 1.0)

            if not (-0.001 <= touch_pct <= _TOUCH_TOL):
                logger.debug("[%s] CHAN_BREAK bullish: low %.2f vs projected %.2f (touch %.3f%%) — no tag",
                             ticker, low_, projected, touch_pct * 100)
                break

            if close <= projected:
                logger.debug("[%s] CHAN_BREAK bullish: close %.2f <= projected %.2f — no bounce",
                             ticker, close, projected)
                break

            if vwap is not None and close <= vwap:
                logger.debug("[%s] CHAN_BREAK bullish: close %.2f <= vwap %.2f", ticker, close, vwap)
                break

            # Block bullish channel bounces in confirmed downtrends
            if msa.classify_trend() == "downtrend":
                logger.debug("[%s] CHAN_BREAK bullish: MSA=downtrend — blocked (counter-trend)", ticker)
                break

            if rvol < rvol_min:
                logger.debug("[%s] CHAN_BREAK bullish: RVOL %.2f < %.2f — skipped", ticker, rvol, rvol_min)
                break

            bounce_body   = (close - low_) / max(high - low_, 0.01)
            channel_age   = curr_idx - sl1["idx"]
            recency_bonus = max(0, 0.05 - channel_age * 0.001)
            rvol_bonus    = min(0.08, max(rvol - rvol_min, 0) * 0.07)
            body_bonus    = min(0.05, bounce_body * 0.06)
            confidence    = min(0.90, 0.75 + rvol_bonus + body_bonus + recency_bonus)

            logger.info(
                "[%s] CHAN_BREAK bullish bounce: sl1=%.2f sl2=%.2f slope=%.4f "
                "projected=%.2f low=%.2f close=%.2f RVOL=%.2f (min=%.2f) conf=%.2f",
                ticker, sl1["price"], sl2["price"], slope,
                projected, low_, close, rvol, rvol_min, confidence,
            )
            return Signal(
                strategy_id = STRATEGY_ID,
                direction   = "bullish",
                trigger_bar = bar_time,
                confidence  = confidence,
                rvol        = rvol,
                meta        = {
                    "trigger":          "ascending_channel_bounce",
                    "sl1_price":        sl1["price"],
                    "sl2_price":        sl2["price"],
                    "slope_per_bar":    round(slope, 4),
                    "projected":        round(projected, 2),
                    "touch_pct":        round(touch_pct * 100, 3),
                    "bounce_body":      round(bounce_body, 2),
                    "entry_bar_low":    round(low_, 4),
                    "rvol_gate":        round(rvol_min, 2),
                    "rvol_gate_reason": _rvol_threshold_reason(
                        bar_min, close, None, vwap, STRATEGY_ID, msa_confirmed=True),
                },
            )

    return None
