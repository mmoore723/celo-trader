"""
strategies/inst_orb.py — Institutional Opening Range Breakout (INST_ORB)

Session window : 09:45 – 10:30 ET
Direction logic:
  • Bullish  — close > OR High and trend is uptrend/consolidation
  • Bearish  — close < OR Low  and trend is downtrend/consolidation
  • Flipped  — failed-breakout fade:
                 bearish-flip  = close > OR High but trend = downtrend
                 bullish-flip  = close < OR Low  but trend = uptrend

Fixes vs. original strategy_router.py
──────────────────────────────────────
1. Per-ticker cooldown  — 20-min window blocks re-entry spam (base.check_cooldown)
2. MFE early-exit gate  — skips signals when price is already overextended:
     non-flip: > 2× ATR past the OR boundary
     flip:     > 1× ATR past the OR boundary (tighter — confirms failed move)
3. VWAP direction fix for flipped signals — the standard "bearish requires close < VWAP"
   gate incorrectly blocks failed-breakout-fade entries (price is above VWAP by design).
   Replaced with a proximity check: price must be within max(ATR, 0.5% of VWAP) of VWAP.
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
    check_cooldown,
    register_cooldown,
)

logger = logging.getLogger("celo_trader.strategies.inst_orb")

STRATEGY_ID = "INST_ORB"

# Session window (minutes since midnight ET)
_SESSION_START = 9 * 60 + 45    # 09:45
_SESSION_END   = 10 * 60 + 30   # 10:30


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    """
    Evaluate INST_ORB signals on the current session's bar data.

    Parameters
    ----------
    today  : DataFrame with columns time, open, high, low, close, volume, rvol, vwap
    ticker : ticker symbol — used for cooldown keying and log context

    Returns
    -------
    Signal if a qualifying setup is found, else None.
    """
    if len(today) < 2:
        return None

    # ── Pre-compute indicators ────────────────────────────────────────────────
    # OR boundaries from signals.get_opening_range(); ATR/VWAP are already
    # columns in today (built by strategy_router._build_indicator_frame).
    or_data = get_opening_range(today)
    if or_data is None:
        return None          # OR not yet formed
    or_high = or_data.get("high")
    or_low  = or_data.get("low")
    if or_high is None or or_low is None:
        return None

    # ── Build market structure once — shared across bar loop ─────────────────
    msa = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()

    # Evaluate on every bar in the session window (most recent qualifying bar wins)
    result: Optional[Signal] = None

    for _, bar in today.iterrows():
        bar_time = bar["time"]
        if not isinstance(bar_time, pd.Timestamp):
            bar_time = pd.Timestamp(bar_time)

        bar_min = bar_time.hour * 60 + bar_time.minute

        # ── Gate 0: session window ────────────────────────────────────────────
        if not (_SESSION_START <= bar_min <= _SESSION_END):
            continue

        close  = float(bar["close"])
        volume = float(bar.get("volume", 0))
        rvol   = float(bar.get("rvol", 0.0))
        _vwap  = bar.get("vwap")
        vwap   = float(_vwap) if (_vwap is not None and not (isinstance(_vwap, float) and np.isnan(_vwap))) else None
        _atr   = bar.get("atr")
        atr    = float(_atr)  if (_atr  is not None and not (isinstance(_atr,  float) and np.isnan(_atr)))  else None

        if atr is None or atr <= 0:
            continue

        # ── Gate 0b: cooldown ─────────────────────────────────────────────────
        if check_cooldown(STRATEGY_ID, ticker, bar_time):
            logger.debug("[%s] %s INST_ORB: cooldown active, skip bar %s", ticker, STRATEGY_ID, bar_time)
            continue

        # ── Determine direction ───────────────────────────────────────────────
        broke_high = close > or_high
        broke_low  = close < or_low

        if not broke_high and not broke_low:
            continue        # price still inside OR — no signal

        direction_flipped = False

        if broke_high:
            if trend in ("uptrend", "consolidation"):
                direction = "bullish"
            else:
                # Price broke above OR High but the trend is down —
                # likely a failed breakout; we fade the move (sell the rejection).
                direction        = "bearish"
                direction_flipped = True
        else:  # broke_low
            if trend in ("downtrend", "consolidation"):
                direction = "bearish"
            else:
                # Price broke below OR Low but trend is up — bullish fakeout fade.
                direction        = "bullish"
                direction_flipped = True

        # ── Gate 1: MFE / overextension ──────────────────────────────────────
        # Skip bars where price has already run too far from the OR boundary.
        # Non-flip: allow up to 2× ATR of extension (catching the initial thrust).
        # Flip:     allow only 1× ATR (failed move should still be near the OR).
        mfe_multiplier = 1.0 if direction_flipped else 2.0

        if direction == "bullish" and not direction_flipped:
            if close > or_high + mfe_multiplier * atr:
                logger.debug(
                    "[%s] INST_ORB bullish MFE gate: close %.2f > or_high %.2f + %.1f×ATR %.2f — overextended, skip",
                    ticker, close, or_high, mfe_multiplier, atr,
                )
                continue
        elif direction == "bearish" and not direction_flipped:
            if close < or_low - mfe_multiplier * atr:
                logger.debug(
                    "[%s] INST_ORB bearish MFE gate: close %.2f < or_low %.2f - %.1f×ATR %.2f — overextended, skip",
                    ticker, close, or_low, mfe_multiplier, atr,
                )
                continue
        elif direction_flipped:
            # Flip: price must be within 1× ATR of the OR boundary it broke
            boundary = or_high if broke_high else or_low
            if abs(close - boundary) > mfe_multiplier * atr:
                logger.debug(
                    "[%s] INST_ORB flip MFE gate: close %.2f too far from boundary %.2f (>%.1f×ATR %.2f), skip",
                    ticker, close, boundary, mfe_multiplier, atr,
                )
                continue

        # ── Gate 2: dynamic RVOL ─────────────────────────────────────────────
        rvol_threshold = _get_dynamic_rvol_threshold(
            bar_min   = bar_min,
            close     = close,
            or_low    = or_low,
            vwap      = vwap,
            strategy_id = STRATEGY_ID,
        )
        rvol_reason = _rvol_threshold_reason(
            bar_min   = bar_min,
            close     = close,
            or_low    = or_low,
            vwap      = vwap,
            strategy_id = STRATEGY_ID,
        )
        if rvol < rvol_threshold:
            logger.debug(
                "[%s] INST_ORB RVOL gate: %.2f < %.2f (%s), skip",
                ticker, rvol, rvol_threshold, rvol_reason,
            )
            continue

        # ── Gate 3: volume spike vs. vol_sma ────────────────────────────────
        vol_sma = today["volume"].mean()
        if vol_sma > 0 and volume < vol_sma * 1.5:
            logger.debug(
                "[%s] INST_ORB vol_sma gate: %.0f < 1.5× sma %.0f, skip",
                ticker, volume, vol_sma,
            )
            continue

        # ── Gate 4: MSA overextension guard ──────────────────────────────────
        # Don't enter if price is already beyond the last confirmed swing high/low
        # in the signal direction — that's chasing a trend that started long ago.
        last_sh = msa.last_swing_high()
        last_sl = msa.last_swing_low()
        if direction == "bullish" and last_sh is not None and close > last_sh:
            logger.debug(
                "[%s] INST_ORB MSA guard: close %.2f > last swing high %.2f, skip",
                ticker, close, last_sh,
            )
            continue
        if direction == "bearish" and last_sl is not None and close < last_sl:
            logger.debug(
                "[%s] INST_ORB MSA guard: close %.2f < last swing low %.2f, skip",
                ticker, close, last_sl,
            )
            continue

        # ── Gate 5: VWAP direction ────────────────────────────────────────────
        # Standard (non-flipped) signals: price must be on the correct side of VWAP.
        # Flipped signals: the standard gate is incorrect because:
        #   • bearish-flip = close > OR High > VWAP  → close >= VWAP is expected
        #   • bullish-flip = close < OR Low < VWAP   → close <= VWAP is expected
        # For flipped signals we instead require price is within max(ATR, 0.5% VWAP)
        # of VWAP — confirming the failed move hasn't screamed too far from value.
        if vwap is not None:
            if not direction_flipped:
                # Standard VWAP side gate
                if direction == "bullish" and close <= vwap:
                    logger.debug("[%s] INST_ORB VWAP gate: bullish but close %.2f <= vwap %.2f, skip", ticker, close, vwap)
                    continue
                if direction == "bearish" and close >= vwap:
                    logger.debug("[%s] INST_ORB VWAP gate: bearish but close %.2f >= vwap %.2f, skip", ticker, close, vwap)
                    continue
            else:
                # Flipped signal: proximity check — price should still be near VWAP
                # (within 1 ATR or 0.5% of VWAP), not screaming away from it.
                vwap_proximity = abs(close - vwap)
                vwap_limit     = max(atr, vwap * 0.005)
                if vwap_proximity > vwap_limit:
                    logger.debug(
                        "[%s] INST_ORB flip VWAP proximity gate: |close %.2f - vwap %.2f| = %.2f > limit %.2f, skip",
                        ticker, close, vwap, vwap_proximity, vwap_limit,
                    )
                    continue

        # ── All gates passed — build signal ───────────────────────────────────
        confidence = _compute_confidence(
            rvol             = rvol,
            rvol_threshold   = rvol_threshold,
            atr              = atr,
            close            = close,
            or_high          = or_high,
            or_low           = or_low,
            direction        = direction,
            direction_flipped = direction_flipped,
            trend            = trend,
        )

        register_cooldown(STRATEGY_ID, ticker, bar_time)

        result = Signal(
            confidence  = confidence,
            strategy_id = STRATEGY_ID,
            direction   = direction,
            rvol        = rvol,
            trigger_bar = bar_time,
            meta        = {
                "or_high"          : or_high,
                "or_low"           : or_low,
                "atr"              : atr,
                "vwap"             : vwap,
                "trend"            : trend,
                "direction_flipped": direction_flipped,
                "rvol_threshold"   : rvol_threshold,
                "rvol_reason"      : rvol_reason,
            },
        )
        logger.info(
            "[%s] INST_ORB signal: direction=%s flipped=%s confidence=%.2f rvol=%.2f trend=%s",
            ticker, direction, direction_flipped, confidence, rvol, trend,
        )

    return result


# ── Confidence scoring ────────────────────────────────────────────────────────

def _compute_confidence(
    rvol: float,
    rvol_threshold: float,
    atr: float,
    close: float,
    or_high: float,
    or_low: float,
    direction: str,
    direction_flipped: bool,
    trend: str,
) -> float:
    """
    0–1 confidence score.
    Components:
      40% — RVOL strength relative to threshold
      30% — proximity to OR boundary (closer = higher quality entry)
      20% — trend alignment (confirmed > consolidation > counter-trend)
      10% — flip quality penalty (flipped signals get a haircut)
    """
    # RVOL component (capped at 3× threshold for scoring)
    rvol_score = min((rvol / max(rvol_threshold, 0.01)) / 3.0, 1.0)

    # Proximity: how many ATRs past the OR boundary is close?
    # 0 ATRs = 1.0, 2 ATRs = 0.0  (linear interpolation)
    boundary = or_high if direction == "bullish" else or_low
    dist_atrs = abs(close - boundary) / atr
    prox_score = max(0.0, 1.0 - dist_atrs / 2.0)

    # Trend alignment
    if direction == "bullish":
        trend_score = 1.0 if trend == "uptrend" else (0.6 if trend == "consolidation" else 0.3)
    else:
        trend_score = 1.0 if trend == "downtrend" else (0.6 if trend == "consolidation" else 0.3)

    # Flip penalty: failed-breakout setups are lower probability
    flip_multiplier = 0.85 if direction_flipped else 1.0

    confidence = (0.40 * rvol_score + 0.30 * prox_score + 0.20 * trend_score + 0.10) * flip_multiplier
    return round(min(confidence, 1.0), 4)
