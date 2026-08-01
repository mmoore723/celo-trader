"""
strategies/fvg/evaluate.py — evaluate(): Fair Value Gap (FVG) with
Liquidity Sweep Confirmation entry logic.

Split out of the old single strategies/fvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer

from strategies.fvg.constants import STRATEGY_ID
from strategies.fvg.state import _consumed_gaps
from strategies.fvg.sweep import _detect_liquidity_sweep

logger = logging.getLogger("celo_trader.strategies.fvg")


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 6:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    if bar_min < 9 * 60 + 45:
        return None

    c_close = float(last_bar["close"])
    c_vwap  = float(last_bar["vwap"]) if not pd.isna(last_bar.get("vwap", np.nan)) else None
    c_rvol  = float(last_bar["rvol"]) if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0
    atr     = float(last_bar["atr"])  if not pd.isna(last_bar.get("atr",  np.nan)) else 0.0
    ema50   = float(last_bar["ema50"]) if not pd.isna(last_bar.get("ema50", np.nan)) else None

    # MSA built once — shared by trend gate and sweep detection
    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()

    look_back = min(20, len(today) - 2)

    for k in range(look_back, 0, -1):
        if k - 1 < 0 or k + 1 >= len(today):
            continue

        b_prev   = today.iloc[k - 1]
        b_middle = today.iloc[k]
        b_next   = today.iloc[k + 1]

        gap_low  = None
        gap_high = None
        direction = None

        if float(b_prev["low"]) > float(b_next["high"]):
            gap_low   = float(b_next["high"])
            gap_high  = float(b_prev["low"])
            direction = "bullish"
        elif float(b_prev["high"]) < float(b_next["low"]):
            gap_low   = float(b_prev["high"])
            gap_high  = float(b_next["low"])
            direction = "bearish"

        if direction is None:
            continue

        gap_width = gap_high - gap_low
        if atr > 0 and gap_width < 0.5 * atr:
            continue

        if not (gap_low <= c_close <= gap_high):
            continue

        if c_rvol < 1.5:
            logger.debug("[%s] FVG %s: RVOL %.2f < 1.5 — skipped", ticker, direction, c_rvol)
            continue

        # Trend + EMA50 alignment — no counter-trend entries
        if direction == "bullish":
            if trend == "downtrend":
                logger.debug("[%s] FVG bullish: MSA=downtrend — counter-trend, skipped", ticker)
                continue
            if ema50 is not None and c_close < ema50:
                logger.debug("[%s] FVG bullish: close %.2f < EMA50 %.2f — below MA, skipped",
                             ticker, c_close, ema50)
                continue
        else:
            if trend == "uptrend":
                logger.debug("[%s] FVG bearish: MSA=uptrend — counter-trend, skipped", ticker)
                continue
            if ema50 is not None and c_close > ema50:
                logger.debug("[%s] FVG bearish: close %.2f > EMA50 %.2f — above MA, skipped",
                             ticker, c_close, ema50)
                continue

        if c_vwap is not None:
            if direction == "bullish" and c_close < c_vwap:
                continue
            if direction == "bearish" and c_close > c_vwap:
                continue

        # Gap deduplication — each unique gap zone fires once per session
        today_str = str(bar_time.date()) if hasattr(bar_time, "date") else str(bar_time)[:10]
        _gap_key  = (ticker, today_str, round(gap_low, 4), round(gap_high, 4))
        if _gap_key in _consumed_gaps:
            logger.debug("[%s] FVG %s: gap [%.4f–%.4f] already consumed — skipped",
                         ticker, direction, gap_low, gap_high)
            continue

        # ── Liquidity sweep confirmation (BOS_MSS logic merged in) ───────────
        # A sweep of a prior swing high/low in the last 15 bars means smart
        # money just ran stops and this FVG is the imbalance left behind in
        # the reversal — highest probability setup (ICT Silver Bullet concept).
        # Without a sweep the gap is still valid but lower conviction.
        gap_ratio      = gap_width / atr if atr > 0 else 1.0
        base_conf      = 0.55 + min(gap_ratio, 2.0) * 0.10 + min(c_rvol - 1.5, 1.0) * 0.05
        sweep_detected = _detect_liquidity_sweep(today, direction, msa)

        if sweep_detected:
            # Full conviction: sweep + FVG = institutional move confirmed
            confidence = min(0.90, base_conf + 0.07)
            sweep_note = "sweep_confirmed"
            logger.info(
                "[%s] FVG %s SWEEP+GAP signal gap=[%.4f–%.4f] RVOL=%.2f conf=%.2f "
                "(sweep of prior swing confirmed — high conviction entry)",
                ticker, direction, gap_low, gap_high, c_rvol, confidence,
            )
        else:
            # Standard FVG without sweep — confidence capped based on EMA50 proximity.
            # EMA50 acts as structural support/resistance. A FVG that forms NEAR EMA50
            # (within 0.1%) has a structural anchor; one far from EMA50 is overextended.
            #   Near EMA50 (≤0.1%): cap = 0.78 — clean structural FVG, allows entry
            #   Far from EMA50 (>0.1%): cap = 0.75 — overextended, lower conviction
            _gap_mid          = (gap_low + gap_high) / 2.0
            _ema_dist_pct     = abs(_gap_mid - ema50) / max(ema50, 1.0) if ema50 else 1.0
            _near_ema         = _ema_dist_pct <= 0.001  # within 0.1%
            _no_sweep_cap     = 0.78 if _near_ema else 0.75
            confidence        = min(_no_sweep_cap, base_conf - 0.05)
            sweep_note        = f"no_sweep_ema_{'near' if _near_ema else 'far'}"
            logger.info(
                "[%s] FVG %s signal gap=[%.4f–%.4f] RVOL=%.2f conf=%.2f "
                "(no sweep — EMA50 dist=%.2f%% cap=%.2f)",
                ticker, direction, gap_low, gap_high, c_rvol, confidence,
                _ema_dist_pct * 100, _no_sweep_cap,
            )

        # Mark gap consumed before returning
        _consumed_gaps.add(_gap_key)
        _stale = {k for k in _consumed_gaps if k[1] < today_str}
        _consumed_gaps.difference_update(_stale)

        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = direction,
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "gap_low":       gap_low,
                "gap_high":      gap_high,
                "gap_width":     gap_width,
                "atr":           atr,
                "vwap":          c_vwap,
                "formed_bar":    b_middle["time"],
                "sweep_detected": sweep_detected,
                "sweep_note":    sweep_note,
            },
        )

    return None
