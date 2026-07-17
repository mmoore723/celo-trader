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

from signals import get_opening_range, get_consolidation_range
from strategies.base import (
    Signal,
    MarketStructureAnalyzer,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
)

logger = logging.getLogger("celo_trader.strategies.mid_brk")

STRATEGY_ID = "MID_BRK"

# ── Consolidation-range reference (2026-07-17) ────────────────────────────────
# OFF by default. The mechanical 15-min opening range can sit well below where
# price actually builds its real morning base — on 2026-07-16 SPY consolidated
# ~753.5-753.9 for 45 min before breaking down, but the 15-min OR low (751.13)
# wasn't touched until after MID_BRK's session window had already closed, so
# the strategy structurally could not catch the real move. When enabled, uses
# the high/low of 09:30-CONSOLIDATION_END_MIN instead of the raw 15-min OR.
# See ab_test_mid_brk_consolidation.py before flipping this live.
CONSOLIDATION_RANGE_ENABLED = False
CONSOLIDATION_END_HOUR      = 10
CONSOLIDATION_END_MINUTE    = 15

# ── Session window (2026-07-17) ───────────────────────────────────────────────
# Named constants instead of a hardcoded literal so diag/ab_test scripts can
# flip _SESSION_END_MIN the same way trend_cont.py's _MAX_BARS gets A/B'd.
# Investigating whether cutting off at 13:00 misses real afternoon breakdowns
# (2026-07-16 SPY's real move didn't clear either reference level until after
# this window closed). See diag_mid_brk_session_scan.py before changing.
_SESSION_START_MIN = 10 * 60 + 30   # 10:30 ET
_SESSION_END_MIN    = 13 * 60        # 13:00 ET


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 10:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window (default 10:30–13:00, see _SESSION_* constants above)
    if not (_SESSION_START_MIN <= bar_min <= _SESSION_END_MIN):
        return None

    if CONSOLIDATION_RANGE_ENABLED:
        or_info = get_consolidation_range(
            today, CONSOLIDATION_END_HOUR, CONSOLIDATION_END_MINUTE)
    else:
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
    # REVERTED 2026-07-17: raised 0.65 -> 0.72 alongside the same change in
    # trend_cont.py, on the hypothesis that the router's 0.74 confidence floor
    # was wrongly killing good signals. Backtest disproved that for TREND_CONT
    # (24 trades / 29% WR / -$39.59 expectancy after the change, was +$41
    # before) — reverting MID_BRK too rather than leave an unverified change
    # live on a now-falsified premise. Only 1 trade in the test window, too
    # few to judge MID_BRK specifically either way.
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
