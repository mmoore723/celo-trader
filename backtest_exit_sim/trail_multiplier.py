"""
backtest_trail_multiplier.py — Real dynamic ATR-trail multiplier for the
backtest exit engine.

Split out of backtest_exit_sim.py (2026-07-21) to keep both files under the
project's 200-line-per-file convention.

Live's position_manager.py doesn't use one flat ATR-trail multiplier for
every trade — it widens the trail when the 1-hour trend supports the trade
(more room for a runner) and tightens it when 5-min RSI is exhausted, 5-min
MACD is fading, or price is sitting right on a 15-min swing level (all
signs the move is running out of room). This module replicates that exact
logic (same thresholds, same stacking order) using the 1h/15m bars
backtester.py fetches alongside the primary 5-min data, instead of the flat
2.0x stand-in this backtest used before today.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from trading.position_manager import (
    _structural_swing_stop,
    _TRAIL_MULT_BASE,
    _TRAIL_MULT_1H_WITH,
    _TRAIL_MULT_1H_AGAINST,
    _TRAIL_MULT_TIGHT,
    _RSI_EXHAUST_CALL,
    _RSI_EXHAUST_PUT,
    _MACD_FADE_BARS,
    _15M_SWING_PROX_PCT,
)
from trading.mtf_features import compute_rsi, compute_macd_hist, trend_bias_1h


def dynamic_trail_multiplier(
    direction: str,
    df_1h_slice: Optional[pd.DataFrame],
    df_5m_slice: pd.DataFrame,
    df_15m_slice: Optional[pd.DataFrame],
) -> float:
    """
    Real replica of position_manager.py's _dynamic_trail_mult logic: 1h trend
    bias sets the baseline, then 5m RSI exhaustion / 5m MACD fade / 15m swing
    proximity can each only tighten it further, never loosen past what 1h
    already set. Falls back to the flat base at every step if data is
    missing or a fetch failed — never blocks a backtest run.
    """
    mult = _TRAIL_MULT_BASE

    bias = trend_bias_1h(df_1h_slice, direction) if df_1h_slice is not None else "neutral"
    if bias == "with":
        mult = _TRAIL_MULT_1H_WITH
    elif bias == "against":
        mult = min(mult, _TRAIL_MULT_1H_AGAINST)

    if df_5m_slice is not None and not df_5m_slice.empty:
        rsi = compute_rsi(df_5m_slice)
        exhausted = (
            (rsi is not None and direction == "bullish" and rsi >= _RSI_EXHAUST_CALL) or
            (rsi is not None and direction == "bearish" and rsi <= _RSI_EXHAUST_PUT)
        )
        if exhausted:
            mult = min(mult, _TRAIL_MULT_TIGHT)

        macd_hist = compute_macd_hist(df_5m_slice)
        if len(macd_hist) >= _MACD_FADE_BARS:
            fading = all(
                macd_hist[-(i + 1)] < macd_hist[-(i + 2)]
                for i in range(_MACD_FADE_BARS - 1)
            )
            if fading:
                mult = min(mult, _TRAIL_MULT_1H_AGAINST)

    if df_15m_slice is not None and not df_15m_slice.empty:
        close_15m = float(df_15m_slice["close"].iloc[-1])
        swing_15m = _structural_swing_stop(df_15m_slice, direction, lookback=20)
        if swing_15m is not None and close_15m > 0:
            prox_pct = abs(close_15m - swing_15m) / close_15m
            if prox_pct <= _15M_SWING_PROX_PCT:
                mult = min(mult, _TRAIL_MULT_TIGHT)

    return mult
