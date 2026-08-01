"""
strategies/trend_cont/evaluate.py — evaluate(): Trend Continuation
(TREND_CONT) entry logic.

Enters on LH re-entry (bearish) or HL re-entry (bullish) — the second/third
entry AFTER trend has already been proven. The pivot must be within
_MAX_BARS bars (fresh, not stale).

Gates:
  1. Session: 09:45–14:30 ET
  2. RVOL ≥ 1.2× (trend already proven; lower threshold than ORB)
  3. MSA confirmed downtrend + LH  OR  uptrend + HL
  4. Pivot ≤ _MAX_BARS bars old
  5. Current bar closes below LH close (bearish) or above HL close (bullish)
  6. VWAP alignment (soft — blocks but logs)

Split out of the old single strategies/trend_cont.py (2026-08-01,
file-size cleanup); no logic changed, only relocated.

_MAX_BARS, _MIN_DEPTH_PCT, and STRUCT_STOP_MODE are read via a live dotted
lookup on the package object (`_pkg.ATTR`) at the top of evaluate(), NOT
via module-level globals defined in this file — see constants.py's
docstring for why (archived A/B scripts monkey-patch these on
`trend_cont.ATTR` directly).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer

from strategies.trend_cont.constants import STRATEGY_ID, _RVOL_MIN

logger = logging.getLogger("celo_trader.strategies.trend_cont")


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 20:
        return None

    # Live dotted lookup on the package namespace — see module docstring for
    # why this can't be a plain module-level global in this file.
    import strategies.trend_cont as _pkg
    _MAX_BARS         = _pkg._MAX_BARS
    _MIN_DEPTH_PCT    = _pkg._MIN_DEPTH_PCT
    STRUCT_STOP_MODE  = _pkg.STRUCT_STOP_MODE

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

    ema50 = float(last_bar["ema50"]) if not pd.isna(last_bar.get("ema50", np.nan)) else None

    # ── BEARISH: downtrend + LH re-entry ─────────────────────────────────────
    # EMA50 gate: price must be below the session EMA50 for bearish entries.
    # Blocks counter-trend shorts on bounces above the moving average.
    if trend == "downtrend" and msa.confirmed_lower_high() and len(highs) >= 2:
        lh       = highs[-1]
        prior_sh = highs[-2]
        bars_ago = curr_idx - lh["idx"]

        if bars_ago > _MAX_BARS:
            logger.debug("[%s] TREND_CONT bearish: LH is %d bars old — stale", ticker, bars_ago)
        else:
            lh_bar_close = float(today.iloc[lh["idx"]]["close"])
            if close < lh_bar_close:
                if ema50 is not None and close > ema50:
                    logger.debug("[%s] TREND_CONT bearish: close %.2f > EMA50 %.2f — micro-trend bounce, skipped", ticker, close, ema50)
                elif vwap is None or close < vwap:
                    lh_depth_pct = (prior_sh["price"] - lh["price"]) / prior_sh["price"]
                    if lh_depth_pct * 100 < _MIN_DEPTH_PCT:
                        logger.debug(
                            "[%s] TREND_CONT bearish: lh_depth_pct %.2f%% < %.2f%% — pullback too shallow",
                            ticker, lh_depth_pct * 100, _MIN_DEPTH_PCT,
                        )
                        return None
                    depth_bonus  = min(0.06, lh_depth_pct * 20)
                    rvol_bonus   = min(0.08, (rvol - _RVOL_MIN) * 0.06)
                    # REVERTED 2026-07-17: base was raised 0.65 -> 0.72 on the
                    # hypothesis that the router's 0.74 floor was wrongly killing
                    # good signals. Real backtest disproved it: with the floor
                    # bypassed, TREND_CONT went to 24 trades / 29% WR / -$39.59
                    # expectancy (was +$41/trade before). The floor was correctly
                    # filtering marginal 0.67-0.72 setups that are net losers, not
                    # blocking good trades. Back to 0.65 — do not raise this again
                    # without a positive backtest first.
                    confidence   = min(0.82, 0.65 + rvol_bonus + depth_bonus)
                    logger.info(
                        "[%s] TREND_CONT bearish LH re-entry: prior_SH=%.2f LH=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        ticker, prior_sh["price"], lh["price"], close, rvol, bars_ago, confidence,
                    )
                    # Structural stop (2026-07-21, research-backed) — this IS a
                    # confirmation/re-entry trade, exactly the case every source
                    # says should carry a tight stop just beyond the pivot that
                    # confirmed it, not the wide ATR fallback it was silently
                    # getting. STRUCT_STOP_MODE picks which level (see constant).
                    if STRUCT_STOP_MODE == "pivot":
                        _struct_ref = lh["price"]
                    elif STRUCT_STOP_MODE == "prior_swing":
                        _struct_ref = prior_sh["price"]
                    elif STRUCT_STOP_MODE == "entry_bar":
                        _struct_ref = float(last_bar["high"])
                    else:   # "none"
                        _struct_ref = None
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
                            "entry_bar_high": _struct_ref,
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
    # EMA50 gate: price must be above the session EMA50 for bullish entries.
    # A "higher low" below EMA50 is a relief bounce inside a downtrend — not a real HL.
    if trend == "uptrend" and msa.confirmed_higher_low() and len(lows) >= 2:
        hl       = lows[-1]
        prior_sl = lows[-2]
        bars_ago = curr_idx - hl["idx"]

        if bars_ago > _MAX_BARS:
            logger.debug("[%s] TREND_CONT bullish: HL is %d bars old — stale", ticker, bars_ago)
        else:
            hl_bar_close = float(today.iloc[hl["idx"]]["close"])
            if close > hl_bar_close:
                if ema50 is not None and close < ema50:
                    logger.debug("[%s] TREND_CONT bullish: close %.2f < EMA50 %.2f — bounce below MA, skipped", ticker, close, ema50)
                elif vwap is None or close > vwap:
                    hl_rise_pct = (hl["price"] - prior_sl["price"]) / prior_sl["price"]
                    if hl_rise_pct * 100 < _MIN_DEPTH_PCT:
                        logger.debug(
                            "[%s] TREND_CONT bullish: hl_rise_pct %.2f%% < %.2f%% — pullback too shallow",
                            ticker, hl_rise_pct * 100, _MIN_DEPTH_PCT,
                        )
                        return None
                    rise_bonus  = min(0.06, hl_rise_pct * 20)
                    rvol_bonus  = min(0.08, (rvol - _RVOL_MIN) * 0.06)
                    # REVERTED 2026-07-17 — see matching note in the bearish branch
                    # above. Real backtest showed the 0.72 base made expectancy
                    # negative; back to 0.65.
                    confidence  = min(0.82, 0.65 + rvol_bonus + rise_bonus)
                    logger.info(
                        "[%s] TREND_CONT bullish HL re-entry: prior_SL=%.2f HL=%.2f "
                        "close=%.2f RVOL=%.2f bars_ago=%d conf=%.2f",
                        ticker, prior_sl["price"], hl["price"], close, rvol, bars_ago, confidence,
                    )
                    # Structural stop (2026-07-21, research-backed) — same
                    # reasoning as the bearish branch above: stop belongs just
                    # beyond the pivot that confirmed this re-entry.
                    if STRUCT_STOP_MODE == "pivot":
                        _struct_ref = hl["price"]
                    elif STRUCT_STOP_MODE == "prior_swing":
                        _struct_ref = prior_sl["price"]
                    elif STRUCT_STOP_MODE == "entry_bar":
                        _struct_ref = float(last_bar["low"])
                    else:   # "none"
                        _struct_ref = None
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
                            "entry_bar_low": _struct_ref,
                        },
                    )
                else:
                    logger.debug("[%s] TREND_CONT bullish: close %.2f <= vwap %.2f", ticker, close, vwap)

    return None
