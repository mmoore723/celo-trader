"""
strategies/trend_cont.py — Trend Continuation (TREND_CONT)

Session: 09:45–14:30 ET | Direction: both

Enters on LH re-entry (bearish) or HL re-entry (bullish) — the second/third
entry AFTER trend has already been proven.  The pivot must be within 20 bars
(fresh, not stale).

Gates:
  1. Session: 09:45–14:30 ET
  2. RVOL ≥ 1.2× (trend already proven; lower threshold than ORB)
  3. MSA confirmed downtrend + LH  OR  uptrend + HL
  4. Pivot ≤ 20 bars old
  5. Current bar closes below LH close (bearish) or above HL close (bullish)
  6. VWAP alignment (soft — blocks but logs)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer

logger = logging.getLogger("celo_trader.strategies.trend_cont")

STRATEGY_ID = "TREND_CONT"

_RVOL_MIN   = 1.2
_MAX_BARS   = 20


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 20:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window 09:45–14:30
    if not (9 * 60 + 45 <= bar_min <= 14 * 60 + 30):
        return None

    rvol  = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    vwap  = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    close = float(last_bar["close"])
    curr_idx = len(today) - 1

    # Gate 2: RVOL
    if rvol < _RVOL_MIN:
        logger.debug("[%s] TREND_CONT: RVOL %.2f < %.1f — skipped", ticker, rvol, _RVOL_MIN)
        return None

    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()
    highs = msa._highs()
    lows  = msa._lows()

    # ── BEARISH: downtrend + LH re-entry ─────────────────────────────────────
    if trend == "downtrend" and msa.confirmed_lower_high() and len(highs) >= 2:
        lh       = highs[-1]
        prior_sh = highs[-2]
        bars_ago = curr_idx - lh["idx"]

        if bars_ago > _MAX_BARS:
            logger.debug("[%s] TREND_CONT bearish: LH is %d bars old — stale", ticker, bars_ago)
        else:
            lh_bar_close = float(today.iloc[lh["idx"]]["close"])
            if close < lh_bar_close:
                if vwap is None or close < vwap:
                    lh_depth_pct = (prior_sh["price"] - lh["price"]) / prior_sh["price"]
                    depth_bonus  = min(0.06, lh_depth_pct * 20)
                    rvol_bonus   = min(0.08, (rvol - _RVOL_MIN) * 0.06)
                    confidence   = min(0.82, 0.65 + rvol_bonus + depth_bonus)
                    logger.info(
                        "[%s] TREND_CONT bearish LH re-entry: prior_SH=%.2f LH=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        ticker, prior_sh["price"], lh["price"], close, rvol, bars_ago, confidence,
                    )
                    return Signal(
                        strategy_id = STRATEGY_ID,
                        direction   = "bearish",
                        trigger_bar = bar_time,
                        confidence  = confidence,
                        rvol        = rvol,
                        meta        = {
                            "trigger":       "lh_reentry",
                            "lh_price":      lh["price"],
                            "prior_sh":      prior_sh["price"],
                            "bars_ago":      bars_ago,
                            "lh_depth_pct":  round(lh_depth_pct * 100, 2),
                        },
                    )
                else:
                    logger.debug("[%s] TREND_CONT bearish: close %.2f >= vwap %.2f", ticker, close, vwap)
            else:
                logger.debug(
                    "[%s] TREND_CONT bearish: close %.2f >= lh_close %.2f — not rolling over yet",
                    ticker, close, lh_bar_close,
                )

    # ── BULLISH: uptrend + HL re-entry ───────────────────────────────────────
    if trend == "uptrend" and msa.confirmed_higher_low() and len(lows) >= 2:
        hl       = lows[-1]
        prior_sl = lows[-2]
        bars_ago = curr_idx - hl["idx"]

        if bars_ago > _MAX_BARS:
            logger.debug("[%s] TREND_CONT bullish: HL is %d bars old — stale", ticker, bars_ago)
        else:
            hl_bar_close = float(today.iloc[hl["idx"]]["close"])
            if close > hl_bar_close:
                if vwap is None or close > vwap:
                    hl_rise_pct = (hl["price"] - prior_sl["price"]) / prior_sl["price"]
                    rise_bonus  = min(0.06, hl_rise_pct * 20)
                    rvol_bonus  = min(0.08, (rvol - _RVOL_MIN) * 0.06)
                    confidence  = min(0.82, 0.65 + rvol_bonus + rise_bonus)
                    logger.info(
                        "[%s] TREND_CONT bullish HL re-entry: prior_SL=%.2f HL=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        ticker, prior_sl["price"], hl["price"], close, rvol, bars_ago, confidence,
                    )
                    return Signal(
                        strategy_id = STRATEGY_ID,
                        direction   = "bullish",
                        trigger_bar = bar_time,
                        confidence  = confidence,
                        rvol        = rvol,
                        meta        = {
                            "trigger":      "hl_reentry",
                            "hl_price":     hl["price"],
                            "prior_sl":     prior_sl["price"],
                            "bars_ago":     bars_ago,
                            "hl_rise_pct":  round(hl_rise_pct * 100, 2),
                        },
                    )
                else:
                    logger.debug("[%s] TREND_CONT bullish: close %.2f <= vwap %.2f", ticker, close, vwap)

    return None
