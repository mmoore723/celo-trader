"""
strategies/chan_break/descending.py — Descending channel (bearish) trendline
rejection detection.

Split out of the old single strategies/chan_break.py (2026-08-01,
file-size cleanup); no logic changed, only relocated as a standalone
helper called from evaluate.py. The bearish and bullish channel searches
were always fully independent (only sharing read-only setup context, no
mutable state between them), so splitting them apart is a safe,
behavior-preserving extraction — not the "irreducible function" exception
used elsewhere in this session.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer, _rvol_threshold_reason
from strategies.chan_break.constants import STRATEGY_ID, _MIN_SLOPE, _MAX_AGE, _TOUCH_TOL

logger = logging.getLogger("celo_trader.strategies.chan_break")


def _evaluate_descending(
    today: pd.DataFrame,
    ticker: str,
    bar_time: pd.Timestamp,
    bar_min: int,
    close: float,
    high: float,
    low_: float,
    curr_idx: int,
    rvol: float,
    rvol_min: float,
    vwap: "float | None",
    atr: float,
    msa: MarketStructureAnalyzer,
    highs: list[dict],
) -> Optional[Signal]:
    """Short at descending channel upper trendline. See package docstring."""
    if len(highs) < 2:
        return None

    for j in range(len(highs) - 1, 0, -1):
        sh2 = highs[j]       # more recent, lower
        sh1 = highs[j - 1]   # older, higher

        if sh2["price"] >= sh1["price"]:
            continue

        if (curr_idx - sh1["idx"]) > _MAX_AGE:
            break

        slope = (sh2["price"] - sh1["price"]) / max(sh2["idx"] - sh1["idx"], 1)
        if abs(slope) < _MIN_SLOPE:
            logger.debug("[%s] CHAN_BREAK: slope %.4f too flat", ticker, slope)
            continue

        projected = sh2["price"] + slope * (curr_idx - sh2["idx"])
        touch_pct = (high - projected) / max(projected, 1.0)

        if not (-0.001 <= touch_pct <= _TOUCH_TOL):
            logger.debug("[%s] CHAN_BREAK bearish: high %.2f vs projected %.2f (touch %.3f%%) — no tag",
                         ticker, high, projected, touch_pct * 100)
            break

        if close >= projected:
            logger.debug("[%s] CHAN_BREAK bearish: close %.2f >= projected %.2f — no rejection",
                         ticker, close, projected)
            break

        # Minimum rejection distance — close must be ≥ 0.3% below the trendline.
        # "Barely below" is noise; real rejections leave clear distance.
        _reject_pct = (projected - close) / max(projected, 1.0)
        if _reject_pct < 0.0015:
            logger.debug("[%s] CHAN_BREAK bearish: rejection %.3f%% < 0.3%% — too shallow",
                         ticker, _reject_pct * 100)
            break

        # Rejection wick — requirement scales with channel width.
        # Wide channels already provide structural security via the two swing
        # highs; a large wick isn't as critical. Tight channels need a strong
        # pin to confirm the rejection isn't noise.
        #   channel width < 0.5%  → require ≥ 40% wick (tight channel, pin required)
        #   channel width > 1.5%  → require ≥ 25% wick (wide channel, structure sufficient)
        #   in between → linear interpolation
        _channel_width_pct = (sh1["price"] - sh2["price"]) / max(sh1["price"], 1.0)
        _wick_req = 0.40 - (0.40 - 0.25) * max(0.0, min(1.0,
            (_channel_width_pct - 0.005) / (0.015 - 0.005)))
        _bar_range  = high - low_
        _upper_wick = high - close
        if _bar_range > 0 and _upper_wick / _bar_range < _wick_req:
            logger.debug("[%s] CHAN_BREAK bearish: upper wick %.0f%% < %.0f%% (channel_width=%.2f%%) — weak rejection",
                         ticker, _upper_wick / _bar_range * 100, _wick_req * 100, _channel_width_pct * 100)
            break

        # Price momentum — price must be moving away from the line.
        # If close ≥ prev close the bar is still rising into resistance.
        _prev_close_bar = float(today.iloc[-2]["close"]) if len(today) >= 2 else close
        if close >= _prev_close_bar:
            logger.debug("[%s] CHAN_BREAK bearish: close %.2f >= prev_close %.2f — no bearish momentum",
                         ticker, close, _prev_close_bar)
            break

        if vwap is not None and close >= vwap:
            logger.debug("[%s] CHAN_BREAK bearish: close %.2f >= vwap %.2f", ticker, close, vwap)
            break

        # Block bearish rejections in confirmed uptrends — counter-trend shorts
        # at the trendline are the #1 cause of losses on this strategy.
        if msa.classify_trend() == "uptrend":
            logger.debug("[%s] CHAN_BREAK bearish: MSA=uptrend — blocked (counter-trend)", ticker)
            break

        if rvol < rvol_min:
            logger.debug("[%s] CHAN_BREAK bearish: RVOL %.2f < %.2f — skipped", ticker, rvol, rvol_min)
            break

        rejection_body = (high - close) / max(high - low_, 0.01)
        channel_age    = curr_idx - sh1["idx"]
        recency_bonus  = max(0, 0.05 - channel_age * 0.001)
        rvol_bonus     = min(0.08, max(rvol - rvol_min, 0) * 0.07)
        body_bonus     = min(0.05, rejection_body * 0.06)
        confidence     = min(0.90, 0.75 + rvol_bonus + body_bonus + recency_bonus)

        logger.info(
            "[%s] CHAN_BREAK bearish rejection: sh1=%.2f sh2=%.2f slope=%.4f "
            "projected=%.2f high=%.2f close=%.2f RVOL=%.2f (min=%.2f) conf=%.2f",
            ticker, sh1["price"], sh2["price"], slope,
            projected, high, close, rvol, rvol_min, confidence,
        )
        # Structural stop for PUTS: use the PREVIOUS bar's high, not the
        # entry bar's own high.  The entry bar's high ≈ the channel trendline
        # (within 0.3% by definition), so using it as the stop means price
        # only needs to move ~0.1% against us before we're stopped.
        # The previous bar's high gives a full bar of breathing room and
        # ties the stop to actual chart structure rather than a point-in-time touch.
        # Stop for PUTS: prev bar's high, floored at current high + 0.5×ATR.
        # The floor prevents a doji prev-bar from producing a zero-width stop —
        # if prev bar's high is barely above current bar's high, we use
        # the ATR-based floor instead so there's always meaningful room.
        _prev_bar_high = float(today.iloc[-2]["high"]) if len(today) >= 2 else high
        _prev_bar_high = max(_prev_bar_high, high + 0.5 * atr)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = "bearish",
            trigger_bar = bar_time,
            confidence  = confidence,
            rvol        = rvol,
            meta        = {
                "trigger":          "descending_channel_rejection",
                "sh1_price":        sh1["price"],
                "sh2_price":        sh2["price"],
                "slope_per_bar":    round(slope, 4),
                "projected":        round(projected, 2),
                "touch_pct":        round(touch_pct * 100, 3),
                "rejection_body":   round(rejection_body, 2),
                "entry_bar_high":   round(_prev_bar_high, 4),   # prev bar's high (floored at high + 0.5×ATR)
                "rvol_gate":        round(rvol_min, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, close, None, vwap, STRATEGY_ID, msa_confirmed=True),
            },
        )

    return None
