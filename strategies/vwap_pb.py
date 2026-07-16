"""
strategies/vwap_pb.py — VWAP Pullback (VWAP_PB)

Trend-continuation pullback to VWAP:
  Bullish: EMA50 + VWAP both rising, price taps VWAP (within 0.2%) then reclaims.
  Bearish: EMA50 + VWAP both falling, price taps VWAP then rejects.

Entry gates (2026-07-15 rework after 10% WR audit):
  • 5-of-5 blowthrough guard  • 0.2% touch proximity  • VWAP slope
  • EMA50 slope  • ADX ≥ 25 regime (enforced in strategy_router)

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

    # ── Blowthrough guard (2026-07-15 rework: 5-of-5, was 3-of-5) ─────────────
    # A true pullback needs price on the correct side of VWAP for ALL recent
    # bars — a single opposing bar means price is crashing THROUGH the level.
    _lookback_bars = today.iloc[-6:-1] if len(today) >= 6 else today.iloc[:-1]

    def _was_above_vwap(bars: pd.DataFrame) -> bool:
        """True only if ALL of the last 5 bars closed above vwap."""
        if len(bars) < 5:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        return all(float(c) > float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))

    def _was_below_vwap(bars: pd.DataFrame) -> bool:
        """True only if ALL of the last 5 bars closed below vwap."""
        if len(bars) < 5:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        return all(float(c) < float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))

    # ── Trend-direction gates (2026-07-15 rework) ─────────────────────────────
    # VWAP slope: don't buy pullbacks to a descending VWAP (distribution) or
    # short bounces off an ascending one. EMA50 slope: level check alone isn't
    # a trend — the docstring promise "EMA50 trending up/down" now enforced.
    _TOUCH_PCT = 0.002   # prev bar must tap within 0.2% of VWAP — a real touch
    if len(today) >= 6:
        _vwap_5ago  = float(today["vwap"].iloc[-6])  if not pd.isna(today["vwap"].iloc[-6])  else c_vwap
        _ema50_5ago = float(today["ema50"].iloc[-6]) if not pd.isna(today["ema50"].iloc[-6]) else c_ema50
    else:
        _vwap_5ago, _ema50_5ago = c_vwap, c_ema50
    _vwap_rising   = c_vwap  > _vwap_5ago
    _vwap_falling  = c_vwap  < _vwap_5ago
    _ema50_rising  = c_ema50 > _ema50_5ago
    _ema50_falling = c_ema50 < _ema50_5ago

    # ── Bullish pullback ──────────────────────────────────────────────────────
    rvol_min_bull = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bull)

    _bull_conditions = (
        c_close > c_ema50 and
        c_vwap  > c_ema50 and
        _ema50_rising and                              # EMA50 actually trending up
        _vwap_rising and                               # never buy a descending VWAP
        p_low  <= p_vwap and                           # prev bar touched VWAP...
        p_low  >= p_vwap * (1.0 - _TOUCH_PCT) and      # ...within 0.2% (tap, not pierce)
        c_close > c_vwap and
        c_rvol >= rvol_min_bull
    )
    if _bull_conditions and not _was_above_vwap(_lookback_bars):
        logger.debug("[%s] VWAP_PB bullish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    if _bull_conditions and _was_above_vwap(_lookback_bars):
        proximity  = max(0.0, 1.0 - abs(p_low - p_vwap) / max(p_vwap * _TOUCH_PCT, 0.01))
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
        _ema50_falling and                             # EMA50 actually trending down
        _vwap_falling and                              # never short an ascending VWAP
        p_high >= p_vwap and                           # prev bar touched VWAP...
        p_high <= p_vwap * (1.0 + _TOUCH_PCT) and      # ...within 0.2% (tap, not pierce)
        c_close < c_vwap and
        c_rvol >= rvol_min_bear
    )
    if _bear_conditions and not _was_below_vwap(_lookback_bars):
        logger.debug("[%s] VWAP_PB bearish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    if _bear_conditions and _was_below_vwap(_lookback_bars):
        proximity  = max(0.0, 1.0 - abs(p_high - p_vwap) / max(p_vwap * _TOUCH_PCT, 0.01))
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
