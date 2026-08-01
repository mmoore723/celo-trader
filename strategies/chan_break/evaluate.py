"""
strategies/chan_break/evaluate.py — evaluate(): shared session/RVOL/ATR
setup, then delegates to the descending (bearish) and ascending (bullish)
channel detectors.

Split out of the old single strategies/chan_break.py (2026-08-01,
file-size cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import MarketStructureAnalyzer, Signal, _get_dynamic_rvol_threshold
from strategies.chan_break.constants import STRATEGY_ID
from strategies.chan_break.descending import _evaluate_descending
from strategies.chan_break.ascending import _evaluate_ascending


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 25:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window 09:45–14:00.
    # Dead zone (12:00–13:30) removed — RVOL gate already filters low-participation
    # mid-day bars. The dead zone was blocking 1.5h of valid channel touches.
    if not (9 * 60 + 45 <= bar_min <= 14 * 60):
        return None

    rvol     = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    vwap     = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    close    = float(last_bar["close"])
    high     = float(last_bar["high"])
    low_     = float(last_bar["low"])
    curr_idx = len(today) - 1

    # RVOL threshold: use CHAN_BREAK's own 1.0× floor rather than the relaxed
    # msa_confirmed=True 0.75× path.  A trendline tag with weak volume is noise
    # — it needs real participation to confirm the rejection/bounce.
    rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, None, vwap, STRATEGY_ID, msa_confirmed=False)

    # 14-period ATR — used as minimum stop width floor so that if the previous
    # bar is a tiny doji, the stop still has at least 0.5× ATR of breathing room.
    # We exclude the current (last) bar and take the 14 bars before it.
    _atr_slice = today.iloc[-15:-1] if len(today) >= 15 else today.iloc[:-1]
    if len(_atr_slice) > 1:
        _prev_close = _atr_slice["close"].shift(1)
        _tr = pd.concat([
            _atr_slice["high"] - _atr_slice["low"],
            (_atr_slice["high"] - _prev_close).abs(),
            (_atr_slice["low"]  - _prev_close).abs(),
        ], axis=1).max(axis=1)
        _atr = float(_tr.mean())
    else:
        _atr = 0.0

    msa   = MarketStructureAnalyzer(today)
    highs = msa._highs()
    lows  = msa._lows()

    # ── DESCENDING CHANNEL: bearish short ────────────────────────────────────
    sig = _evaluate_descending(
        today, ticker, bar_time, bar_min, close, high, low_, curr_idx,
        rvol, rvol_min, vwap, _atr, msa, highs,
    )
    if sig is not None:
        return sig

    # ── ASCENDING CHANNEL: bullish long ──────────────────────────────────────
    sig = _evaluate_ascending(
        today, ticker, bar_time, bar_min, close, high, low_, curr_idx,
        rvol, rvol_min, vwap, _atr, msa, lows,
    )
    if sig is not None:
        return sig

    return None
