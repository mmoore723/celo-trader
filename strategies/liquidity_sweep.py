"""
strategies/liquidity_sweep.py — Liquidity Sweep Reversal (LIQ_SWEEP)

Session: 09:45-15:30 ET | Direction: opposite the wick (fades the sweep)
Added 2026-07-31, researched against 10+ outside sources before building.

Entry — fade a failed breakout, confirmed one bar later:
  Bar N-1 ("sweep bar"): wick pierces a recent swing high/low (same
  MarketStructureAnalyzer detector every other strategy uses) by
  >=0.15 ATR, then closes back past the level by >=0.10 ATR.
  Bar N ("confirm bar", the trigger): must NOT make a new extreme past the
  sweep wick, and must close no further back toward it than the sweep bar
  did. Entry fires on bar N's close. RVOL gate checked on the confirm bar.

FIX 2026-08-01 (delayed confirmation): originally fired on the sweep bar's
own close; real trade data showed 84-95% failure. 10+ practitioner sources
(ICT/Judas-swing, Bookmap, Trinity Trading, dailypriceaction, Equiti,
B2PRIME) agree fading the sweep candle's own close is the textbook
premature entry. Moved confirmation to the next candle.

FIX 2026-08-01 (trend headwind): same research flagged "swept = auto-
reversal" as a trap when a strong trend backs the swept direction. Soft
confidence penalty (not a hard block, rule 12) when ADX>25 and the EMA
stack both oppose our fade.

Stop: wick extreme + 0.5*sqrt(5)*ATR. `atr` is 1-min-scale (entries run at
1-min resolution) but the exit engine checks 5-min bar extremes; sqrt(5)
corrects that resolution mismatch (5-min range ≈ sqrt(5)x 1-min range).

UNTESTED against the confirmation-delay + trend-penalty changes — run a
fresh backtest before trusting live sizing.
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
    check_cooldown,
    register_cooldown,
)
from trading.mtf_features import compute_adx, ema_stack_aligned

logger = logging.getLogger("celo_trader.strategies.liquidity_sweep")

STRATEGY_ID = "LIQ_SWEEP"

_SESSION_START_MIN   = 9 * 60 + 45    # 09:45 ET — skip the noisy open
_SESSION_END_MIN     = 15 * 60 + 30   # 15:30 ET — skip the closing drive
_PENETRATION_ATR_MIN = 0.15   # wick must clear the level by this many ATRs
_REJECTION_ATR_MIN   = 0.10   # sweep bar's close must come back this far
_TREND_ADX_MIN        = 25    # ADX above this + aligned EMA stack = headwind
_TREND_HEADWIND_PENALTY = 0.08
_ATR_5MIN_SCALE = 5 ** 0.5    # 1-min ATR -> 5-min-bar-equivalent range


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 9:
        return None

    confirm_bar = today.iloc[-1]   # confirming candle — this is the entry trigger
    sweep_bar   = today.iloc[-2]   # candle whose wick did the sweep

    bar_time = confirm_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute
    if not (_SESSION_START_MIN <= bar_min <= _SESSION_END_MIN):
        return None
    if check_cooldown(STRATEGY_ID, ticker, bar_time):
        return None

    _atr = confirm_bar.get("atr")
    atr  = float(_atr) if (_atr is not None and not (isinstance(_atr, float) and np.isnan(_atr))) else None
    if atr is None or atr <= 0:
        return None

    # Swing levels from everything BEFORE the sweep bar, so neither the sweep
    # nor confirm bar can count as their own pivot.
    msa        = MarketStructureAnalyzer(today.iloc[:-2])
    swing_high = msa.last_swing_high()
    swing_low  = msa.last_swing_low()

    sweep_high, sweep_low, sweep_close = (
        float(sweep_bar["high"]), float(sweep_bar["low"]), float(sweep_bar["close"]))
    c_high, c_low, c_close = (
        float(confirm_bar["high"]), float(confirm_bar["low"]), float(confirm_bar["close"]))
    rvol = float(confirm_bar["rvol"]) if not pd.isna(confirm_bar.get("rvol", np.nan)) else 0.0

    direction: Optional[str] = None
    swept_level: Optional[float] = None
    wick_extreme: Optional[float] = None

    # High sweep on the PRIOR bar → fade DOWN, confirmed by THIS bar
    if swing_high is not None and sweep_high > swing_high + _PENETRATION_ATR_MIN * atr:
        if sweep_close < swing_high - _REJECTION_ATR_MIN * atr:
            if c_high < sweep_high and c_close <= sweep_close:
                direction, swept_level, wick_extreme = "bearish", swing_high, sweep_high

    # Low sweep on the PRIOR bar → fade UP, confirmed by THIS bar
    if direction is None and swing_low is not None and sweep_low < swing_low - _PENETRATION_ATR_MIN * atr:
        if sweep_close > swing_low + _REJECTION_ATR_MIN * atr:
            if c_low > sweep_low and c_close >= sweep_close:
                direction, swept_level, wick_extreme = "bullish", swing_low, sweep_low

    if direction is None:
        return None

    rvol_min = _get_dynamic_rvol_threshold(bar_min, c_close, None, None, STRATEGY_ID, msa_confirmed=False)
    if rvol < rvol_min:
        logger.debug("[%s] LIQ_SWEEP: RVOL %.2f < %.2f — skipped", ticker, rvol, rvol_min)
        return None

    penetration_atrs = abs(wick_extreme - swept_level) / atr
    rejection_atrs    = abs(sweep_close - swept_level) / atr

    rejection_score = min(rejection_atrs, 1.0)
    penetration_score = min(penetration_atrs, 1.0)
    rvol_score = min(max(rvol - rvol_min, 0.0) / max(rvol_min, 0.01), 1.0)
    confidence = min(0.82, 0.60 + 0.15 * rejection_score + 0.05 * penetration_score + 0.10 * rvol_score)

    # Soft trend-headwind penalty — see module docstring.
    adx = compute_adx(today)
    against_direction = "bullish" if direction == "bearish" else "bearish"
    trend_headwind = bool(adx is not None and adx > _TREND_ADX_MIN and ema_stack_aligned(today, against_direction))
    if trend_headwind:
        confidence = max(0.50, confidence - _TREND_HEADWIND_PENALTY)

    if direction == "bearish":
        stop_ref = wick_extreme + 0.5 * _ATR_5MIN_SCALE * atr
    else:
        stop_ref = wick_extreme - 0.5 * _ATR_5MIN_SCALE * atr

    register_cooldown(STRATEGY_ID, ticker, bar_time)
    logger.info(
        "[%s] LIQ_SWEEP %s — swept %.2f, wick %.2f (%.2f ATR), confirm close %.2f, "
        "stop_ref=%.2f, RVOL=%.2f conf=%.2f trend_headwind=%s",
        ticker, direction, swept_level, wick_extreme, penetration_atrs, c_close,
        stop_ref, rvol, confidence, trend_headwind,
    )
    return Signal(
        strategy_id = STRATEGY_ID,
        direction   = direction,
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "swept_level":      swept_level,
            "wick_extreme":     wick_extreme,
            "penetration_atrs": round(penetration_atrs, 2),
            "rejection_atrs":   round(rejection_atrs, 2),
            "rvol_gate":        round(rvol_min, 2),
            "rvol_gate_reason": _rvol_threshold_reason(bar_min, c_close, None, None, STRATEGY_ID, msa_confirmed=False),
            "trend_headwind":   trend_headwind,
            "entry_bar_high": round(stop_ref, 4) if direction == "bearish" else None,
            "entry_bar_low":  round(stop_ref, 4) if direction == "bullish" else None,
        },
    )
