"""
strategies/bos_mss.py — Break of Structure / Market Structure Shift (BOS_MSS)

Fires on the LAST bar of today's data (call on every tick; let route_signals
pass a full session slice so the evaluator can read the most recent bar).

Entry conditions:
  • Price breaks above the last confirmed swing high (bullish BOS) with:
      - FVG confirmation (imbalance evidence within last 20 bars)
      - RVOL ≥ 1.5×
      - EMA50 price alignment (close > EMA50 for bullish, < for bearish)
      - VWAP alignment (close > VWAP for bullish, < for bearish)
  • Mirror for bearish BOS (break below last confirmed swing low).

Fixes vs. original strategy_router.py
──────────────────────────────────────
1. Per-ticker cooldown  — 20-min window (base.check_cooldown / register_cooldown)
2. MFE early-exit gate  — skips if price already > 1.5× ATR past the BOS level:
     bullish: close > prior_hi + 1.5 × ATR  → already ran, chasing
     bearish: close < prior_lo - 1.5 × ATR  → already ran, chasing
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

import numpy as np
from signals import get_opening_range
from strategies.base import (
    Signal,
    MarketStructureAnalyzer,
    _has_recent_fvg,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
    check_cooldown,
    register_cooldown,
)

logger = logging.getLogger("celo_trader.strategies.bos_mss")

STRATEGY_ID = "BOS_MSS"

# Minimum session bars before BOS_MSS is eligible to fire
_MIN_BARS = 10

# RVOL floor for BOS_MSS (structure-confirmed, so relaxed slightly)
_RVOL_FLOOR = 1.5


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    """
    Evaluate BOS_MSS on the current session data slice.

    Only the LAST bar triggers — this prevents spamming a signal every bar once
    structure has broken. route_signals() should call this every tick; we'll
    read the freshest bar here.

    Parameters
    ----------
    today  : DataFrame with columns time, open, high, low, close, volume, rvol, vwap
    ticker : ticker symbol — used for cooldown keying and log context

    Returns
    -------
    Signal if BOS qualifies, else None.
    """
    if len(today) < _MIN_BARS:
        return None

    # Work only with the last bar (trigger bar)
    bar     = today.iloc[-1]
    bar_time = bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)

    bar_min = bar_time.hour * 60 + bar_time.minute
    close   = float(bar["close"])
    rvol    = float(bar.get("rvol", 0.0))
    _vwap   = bar.get("vwap")
    vwap    = float(_vwap) if (_vwap is not None and not (isinstance(_vwap, float) and np.isnan(_vwap))) else None

    # ── Gate 0: cooldown ─────────────────────────────────────────────────────
    if check_cooldown(STRATEGY_ID, ticker, bar_time):
        logger.debug("[%s] BOS_MSS: cooldown active, skip %s", ticker, bar_time)
        return None

    # ── Build market structure ────────────────────────────────────────────────
    msa = MarketStructureAnalyzer(today)

    prior_hi = msa.last_swing_high()
    prior_lo = msa.last_swing_low()

    if prior_hi is None or prior_lo is None:
        logger.debug("[%s] BOS_MSS: insufficient swing history, skip", ticker)
        return None

    # ── Determine direction ───────────────────────────────────────────────────
    broke_above = close > prior_hi
    broke_below = close < prior_lo

    if not broke_above and not broke_below:
        return None      # price is inside swing range — no BOS

    direction = "bullish" if broke_above else "bearish"
    bos_level = prior_hi if broke_above else prior_lo

    # ── Gate 1: MFE / overextension ──────────────────────────────────────────
    # ATR is pre-computed in _build_indicator_frame as the "atr" column.
    _atr_val = bar.get("atr")
    atr      = float(_atr_val) if (_atr_val is not None and not (isinstance(_atr_val, float) and np.isnan(_atr_val))) else None

    if atr and atr > 0:
        mfe_limit = 1.5 * atr
        if direction == "bullish" and close > prior_hi + mfe_limit:
            logger.debug(
                "[%s] BOS_MSS bullish MFE gate: close %.2f > prior_hi %.2f + 1.5×ATR %.2f — overextended, skip",
                ticker, close, prior_hi, atr,
            )
            return None
        if direction == "bearish" and close < prior_lo - mfe_limit:
            logger.debug(
                "[%s] BOS_MSS bearish MFE gate: close %.2f < prior_lo %.2f - 1.5×ATR %.2f — overextended, skip",
                ticker, close, prior_lo, atr,
            )
            return None

    # ── Gate 2: FVG confirmation ──────────────────────────────────────────────
    # Require at least one recent Fair Value Gap in the signal direction —
    # confirms there was institutional imbalance driving the structure break.
    if not _has_recent_fvg(today, direction, lookback=20):
        logger.debug("[%s] BOS_MSS: no recent FVG in %s direction, skip", ticker, direction)
        return None

    # ── Gate 3: RVOL ─────────────────────────────────────────────────────────
    _or     = get_opening_range(today)
    or_low  = _or.get("low") if _or else None

    rvol_threshold = max(
        _get_dynamic_rvol_threshold(
            bar_min     = bar_min,
            close       = close,
            or_low      = or_low,
            vwap        = vwap,
            strategy_id = STRATEGY_ID,
            msa_confirmed = True,
        ),
        _RVOL_FLOOR,        # BOS_MSS floor = 1.5× regardless of context
    )
    rvol_reason = _rvol_threshold_reason(
        bar_min     = bar_min,
        close       = close,
        or_low      = or_low,
        vwap        = vwap,
        strategy_id = STRATEGY_ID,
        msa_confirmed = True,
    )
    if rvol < rvol_threshold:
        logger.debug(
            "[%s] BOS_MSS RVOL gate: %.2f < %.2f (%s), skip",
            ticker, rvol, rvol_threshold, rvol_reason,
        )
        return None

    # ── Gate 4: EMA50 alignment ──────────────────────────────────────────────
    if len(today) >= 50:
        ema50 = float(today["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        if direction == "bullish" and close <= ema50:
            logger.debug("[%s] BOS_MSS EMA50 gate: bullish but close %.2f <= ema50 %.2f, skip", ticker, close, ema50)
            return None
        if direction == "bearish" and close >= ema50:
            logger.debug("[%s] BOS_MSS EMA50 gate: bearish but close %.2f >= ema50 %.2f, skip", ticker, close, ema50)
            return None
    else:
        ema50 = None

    # ── Gate 5: VWAP alignment ───────────────────────────────────────────────
    # Standard directional gate — BOS_MSS direction is not flipped, so the logic
    # is straightforward. (Contrast with INST_ORB flip logic in inst_orb.py.)
    if vwap is not None:
        if direction == "bullish" and close <= vwap:
            logger.debug("[%s] BOS_MSS VWAP gate: bullish but close %.2f <= vwap %.2f, skip", ticker, close, vwap)
            return None
        if direction == "bearish" and close >= vwap:
            logger.debug("[%s] BOS_MSS VWAP gate: bearish but close %.2f >= vwap %.2f, skip", ticker, close, vwap)
            return None

    # ── All gates passed — build signal ───────────────────────────────────────
    confidence = _compute_confidence(
        rvol           = rvol,
        rvol_threshold = rvol_threshold,
        atr            = atr or 0.0,
        close          = close,
        bos_level      = bos_level,
        direction      = direction,
        trend          = msa.classify_trend(),
    )

    register_cooldown(STRATEGY_ID, ticker, bar_time)

    sig = Signal(
        confidence  = confidence,
        strategy_id = STRATEGY_ID,
        direction   = direction,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "prior_hi"       : prior_hi,
            "prior_lo"       : prior_lo,
            "bos_level"      : bos_level,
            "atr"            : atr,
            "vwap"           : vwap,
            "ema50"          : ema50,
            "trend"          : msa.classify_trend(),
            "rvol_threshold" : rvol_threshold,
            "rvol_reason"    : rvol_reason,
        },
    )
    logger.info(
        "[%s] BOS_MSS signal: direction=%s bos_level=%.2f confidence=%.2f rvol=%.2f",
        ticker, direction, bos_level, confidence, rvol,
    )
    return sig


# ── Confidence scoring ────────────────────────────────────────────────────────

def _compute_confidence(
    rvol: float,
    rvol_threshold: float,
    atr: float,
    close: float,
    bos_level: float,
    direction: str,
    trend: str,
) -> float:
    """
    0–1 confidence score.
    Components:
      45% — RVOL strength relative to floor (1.5×)
      30% — proximity to BOS level (0 ATRs = full score, 1.5 ATRs = 0)
      25% — trend confirmation
    """
    rvol_score = min((rvol / max(rvol_threshold, 0.01)) / 2.5, 1.0)

    dist_atrs  = abs(close - bos_level) / atr if atr > 0 else 0.0
    prox_score = max(0.0, 1.0 - dist_atrs / 1.5)

    aligned    = (direction == "bullish" and trend == "uptrend") or \
                 (direction == "bearish" and trend == "downtrend")
    trend_score = 1.0 if aligned else (0.6 if trend == "consolidation" else 0.3)

    confidence = 0.45 * rvol_score + 0.30 * prox_score + 0.25 * trend_score
    return round(min(confidence, 1.0), 4)
