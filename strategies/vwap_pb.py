"""
strategies/vwap_pb.py — VWAP Pullback (VWAP_PB)

Trend-continuation pullback to VWAP:
  Bullish: EMA50 trending up, price dips to VWAP on prior bar then reclaims it.
  Bearish: EMA50 trending down, price bounces to VWAP on prior bar then rejects.

Session: 09:45–EOD  (skips opening chaos)
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

logger = logging.getLogger("celo_trader.strategies.vwap_pb")

STRATEGY_ID = "VWAP_PB"


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 8:
        return None

    prev = today.iloc[-2]
    curr = today.iloc[-1]

    bar_time = curr["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    if bar_min < 9 * 60 + 45:
        return None

    c_close = float(curr["close"])
    c_vwap  = float(curr["vwap"])  if not pd.isna(curr.get("vwap", np.nan)) else None
    c_rvol  = float(curr["rvol"])  if not pd.isna(curr.get("rvol", np.nan)) else 0.0
    c_ema50 = float(curr["ema50"]) if not pd.isna(curr.get("ema50", np.nan)) else c_close

    p_low  = float(prev["low"])
    p_high = float(prev["high"])
    p_vwap = float(prev["vwap"]) if not pd.isna(prev.get("vwap", np.nan)) else None

    if c_vwap is None or p_vwap is None:
        return None

    msa          = MarketStructureAnalyzer(today)
    msa_ok_bull  = msa.confirmed_higher_low()
    msa_ok_bear  = msa.confirmed_lower_high()

    # ── Blowthrough guard ─────────────────────────────────────────────────────
    # A true VWAP pullback requires price to have been ABOVE VWAP (bullish) or
    # BELOW VWAP (bearish) for the majority of recent bars before the touch.
    # Without this, the strategy fires when price is crashing THROUGH VWAP
    # (a continuation move, not a pullback), which produces losing entries.
    # We require ≥ 3 of the last 5 bars (loosened from 4) on the correct side.
    _lookback_bars = today.iloc[-6:-1] if len(today) >= 6 else today.iloc[:-1]

    def _was_above_vwap(bars: pd.DataFrame) -> bool:
        """True if ≥ 3 of the last 5 bars had close > vwap (price was trending above)."""
        if len(bars) < 3:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        _above  = sum(float(c) > float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))
        return _above >= 3

    def _was_below_vwap(bars: pd.DataFrame) -> bool:
        """True if ≥ 3 of the last 5 bars had close < vwap (price was trending below)."""
        if len(bars) < 3:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        _below  = sum(float(c) < float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))
        return _below >= 3

    # ── Bullish pullback ──────────────────────────────────────────────────────
    rvol_min_bull = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bull)

    _bull_conditions = (
        c_close > c_ema50 and
        c_vwap  > c_ema50 and
        p_low  <= p_vwap and
        c_close > c_vwap and
        c_rvol >= rvol_min_bull
    )
    if _bull_conditions and not _was_above_vwap(_lookback_bars):
        logger.debug("[%s] VWAP_PB bullish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    if _bull_conditions and _was_above_vwap(_lookback_bars):
        proximity  = max(0.0, 1.0 - abs(p_low - p_vwap) / max(p_vwap * 0.005, 0.01))
        confidence = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - rvol_min_bull, 1.0) * 0.07)
        logger.info("[%s] VWAP_PB bullish RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
                    ticker, c_rvol, rvol_min_bull, msa_ok_bull, confidence)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = "bullish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "vwap":           c_vwap,
                "ema50":          c_ema50,
                "prev_low":       p_low,
                "vwap_touch":     p_low <= p_vwap,
                "entry_bar_low":  float(curr["low"]),
                "msa_confirmed":  msa_ok_bull,
                "rvol_gate":        round(rvol_min_bull, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bull),
            },
        )

    # ── Bearish pullback ──────────────────────────────────────────────────────
    rvol_min_bear = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bear)

    _bear_conditions = (
        c_close < c_ema50 and
        c_vwap  < c_ema50 and
        p_high >= p_vwap and
        c_close < c_vwap and
        c_rvol >= rvol_min_bear
    )
    if _bear_conditions and not _was_below_vwap(_lookback_bars):
        logger.debug("[%s] VWAP_PB bearish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    if _bear_conditions and _was_below_vwap(_lookback_bars):
        proximity  = max(0.0, 1.0 - abs(p_high - p_vwap) / max(p_vwap * 0.005, 0.01))
        confidence = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - rvol_min_bear, 1.0) * 0.07)
        logger.info("[%s] VWAP_PB bearish RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
                    ticker, c_rvol, rvol_min_bear, msa_ok_bear, confidence)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = "bearish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "vwap":            c_vwap,
                "ema50":           c_ema50,
                "prev_high":       p_high,
                "vwap_touch":      p_high >= p_vwap,
                "entry_bar_high":  float(curr["high"]),
                "msa_confirmed":   msa_ok_bear,
                "rvol_gate":        round(rvol_min_bear, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bear),
            },
        )

    return None
