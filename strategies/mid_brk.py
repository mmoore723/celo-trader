"""
strategies/mid_brk.py — Mid-Day Breakdown (MID_BRK)

Session: 10:30–13:00 ET | Direction: bearish (SHORT/PUT)

After the opening range plays out, if price collapses below OR Low with VWAP
as resistance AND structure has already printed a Lower High, the bias flips
strongly bearish.

Gates:
  1. Session: 10:30–13:00 ET
  2. Price < OR Low
  3. Price < VWAP
  4. MSA confirmed Lower High
  5. Volume > vol_sma20 × 1.5
  6. Dynamic RVOL (msa_confirmed=True → 0.75× floor)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from signals import get_opening_range
from strategies.base import (
    Signal,
    MarketStructureAnalyzer,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
)

logger = logging.getLogger("celo_trader.strategies.mid_brk")

STRATEGY_ID = "MID_BRK"


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 10:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window 10:30–13:00
    if not (10 * 60 + 30 <= bar_min <= 13 * 60):
        return None

    or_info = get_opening_range(today)
    if or_info is None:
        return None

    close   = float(last_bar["close"])
    vwap    = float(last_bar["vwap"])      if not pd.isna(last_bar.get("vwap",     np.nan)) else None
    rvol    = float(last_bar["rvol"])      if not pd.isna(last_bar.get("rvol",     np.nan)) else 0.0
    vol     = float(last_bar["volume"])
    vol_sma = float(last_bar["vol_sma20"]) if not pd.isna(last_bar.get("vol_sma20", np.nan)) else 0.0
    or_low  = or_info["low"]
    or_high = or_info["high"]

    # Gate 2: price below OR Low
    if close >= or_low:
        logger.debug("[%s] MID_BRK: close %.2f >= or_low %.2f — no breakdown", ticker, close, or_low)
        return None

    # Gate 3: price below VWAP
    if vwap is not None and close >= vwap:
        logger.debug("[%s] MID_BRK: close %.2f >= vwap %.2f — no VWAP resistance", ticker, close, vwap)
        return None

    # Gate 4: MSA confirmed Lower High
    msa = MarketStructureAnalyzer(today)
    if not msa.confirmed_lower_high():
        logger.debug("[%s] MID_BRK: no confirmed LH — skipped", ticker)
        return None

    # Gate 5: REMOVED — the intraday rolling vol_sma is inflated by the opening
    # spike bar, making it impossible to clear 1.5× on stocks with high-volume
    # opens (e.g. NFLX gap down with 20x RVOL). Gate 6 (dynamic RVOL) already
    # handles volume confirmation using a proper 10-day baseline — Gate 5 was
    # redundant and actively blocking valid setups.

    # Gate 6: dynamic RVOL (msa confirmed above)
    rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, or_low, vwap, STRATEGY_ID, msa_confirmed=True)
    if rvol < rvol_min:
        logger.debug("[%s] MID_BRK: RVOL %.2f < %.1f — skipped", ticker, rvol, rvol_min)
        return None

    trend       = msa.classify_trend()
    trend_bonus = 0.05 if trend == "downtrend" else 0.0
    breakdown_pct = (or_low - close) / or_low
    mag_bonus     = min(0.04, breakdown_pct * 5)
    confidence    = min(0.86, 0.65 + min(rvol - 1.0, 2.0) * 0.04 + trend_bonus + mag_bonus)

    logger.info("[%s] MID_BRK bearish close=%.2f or_low=%.2f RVOL=%.2f trend=%s conf=%.2f",
                ticker, close, or_low, rvol, trend, confidence)
    return Signal(
        strategy_id = STRATEGY_ID,
        direction   = "bearish",
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "or_low":         or_low,
            "or_high":        or_high,
            "vwap":           vwap,
            "trend":          trend,
            "lh_confirmed":   True,
            "breakdown_pct":  round(breakdown_pct * 100, 2),
            "rvol_gate":        round(rvol_min, 2),
            "rvol_gate_reason": _rvol_threshold_reason(
                bar_min, close, or_low, vwap, STRATEGY_ID, msa_confirmed=True),
        },
    )
