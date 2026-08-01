"""
strategies/mid_brk.py — Mid-Day Breakdown (MID_BRK)

Session: 10:30–13:00 ET | Direction: bearish (SHORT/PUT)

After the opening range plays out, if price collapses below OR Low with VWAP
as resistance AND structure has already printed a Lower High, the bias flips
strongly bearish.

Gates:
  1. Session: 10:30–13:00 ET
  2. Price < OR Low
  3. Price < VWAP
  4. MSA confirmed Lower High
  5. Volume > vol_sma20 × 1.5
  6. Dynamic RVOL (msa_confirmed=True → 0.75× floor)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from signals import get_opening_range, get_consolidation_range
from strategies.base import (
    Signal,
    MarketStructureAnalyzer,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
)

logger = logging.getLogger("celo_trader.strategies.mid_brk")

STRATEGY_ID = "MID_BRK"

# ── Consolidation-range reference (2026-07-17) ─────────────────────────────
# OFF by default. The mechanical 15-min OR can sit well below where price
# actually builds its real morning base (2026-07-16 SPY: real base held at
# 753.5-753.9, but the 15-min OR low wasn't touched until after this
# strategy's session window closed). When enabled, uses 09:30-
# CONSOLIDATION_END_MIN instead of the raw 15-min OR. A/B before flipping.
CONSOLIDATION_RANGE_ENABLED = False
CONSOLIDATION_END_HOUR      = 10
CONSOLIDATION_END_MINUTE    = 15

# ── Session window (2026-07-17) ────────────────────────────────────────────
_SESSION_START_MIN = 10 * 60 + 30   # 10:30 ET
_SESSION_END_MIN    = 13 * 60        # 13:00 ET

# ── Structural stop reference (2026-07-22, A/B tested) ────────────────────
# ab_test_structural_stop_mode.py ran all 4 on SPY/QQQ, 2mo: prior_swing won
# clearly on both expectancy and win rate, beating even ATR-only. Tighter
# options (pivot, entry_bar) got hit by normal noise before the trade had a
# chance to work.
#   "prior_swing" — swing high BEFORE the LH (wider) — DEFAULT, A/B winner
#   "pivot"       — the LH price that confirmed this entry
#   "entry_bar"   — this bar's own high (tightest)
#   "none"        — no structural stop; ATR fallback only
STRUCT_STOP_MODE = "prior_swing"

# ── RVOL ceiling (2026-07-22 hypothesis, ENABLED 2026-08-01) ───────────────
# The RVOL floor rarely binds, so it isn't selecting FOR high RVOL. This
# bot's own A/B-tested data shows the opposite of naive breakout theory: WR
# 44% at RVOL<1.5 vs 9% at RVOL>3.0 — MID_BRK's RVOL check happens at LH-
# confirmation (after the break), so a late volume spike usually reads as
# exhaustion, not fresh conviction. Confirmed again 2026-08-01: this
# session's only 3 wins of 26 all sat in the lowest RVOL bucket; every
# higher bucket was 0%. Soft skip (rule 12), not a hard block on the
# strategy — MID_BRK still trades, just not on exhaustion-shaped entries.
RVOL_CEILING = 2.0   # reject entries where RVOL > 2.0x


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 10:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window (default 10:30–13:00, see _SESSION_* constants above)
    if not (_SESSION_START_MIN <= bar_min <= _SESSION_END_MIN):
        return None

    if CONSOLIDATION_RANGE_ENABLED:
        or_info = get_consolidation_range(
            today, CONSOLIDATION_END_HOUR, CONSOLIDATION_END_MINUTE)
    else:
        or_info = get_opening_range(today)
    if or_info is None:
        return None

    close   = float(last_bar["close"])
    vwap    = float(last_bar["vwap"])      if not pd.isna(last_bar.get("vwap",     np.nan)) else None
    rvol    = float(last_bar["rvol"])      if not pd.isna(last_bar.get("rvol",     np.nan)) else 0.0
    vol     = float(last_bar["volume"])
    vol_sma = float(last_bar["vol_sma20"]) if not pd.isna(last_bar.get("vol_sma20", np.nan)) else 0.0
    or_low  = or_info["low"]
    or_high = or_info["high"]

    # Gate 2: price below OR Low
    if close >= or_low:
        logger.debug("[%s] MID_BRK: close %.2f >= or_low %.2f — no breakdown", ticker, close, or_low)
        return None

    # Gate 3: price below VWAP
    if vwap is not None and close >= vwap:
        logger.debug("[%s] MID_BRK: close %.2f >= vwap %.2f — no VWAP resistance", ticker, close, vwap)
        return None

    # Gate 4: MSA confirmed Lower High
    msa = MarketStructureAnalyzer(today)
    if not msa.confirmed_lower_high():
        logger.debug("[%s] MID_BRK: no confirmed LH — skipped", ticker)
        return None

    # Gate 5: REMOVED — the intraday rolling vol_sma is inflated by the opening
    # spike bar, making it impossible to clear 1.5× on stocks with high-volume
    # opens (e.g. NFLX gap down with 20x RVOL). Gate 6 (dynamic RVOL) already
    # handles volume confirmation using a proper 10-day baseline — Gate 5 was
    # redundant and actively blocking valid setups.

    # Gate 6: dynamic RVOL (msa confirmed above)
    rvol_min = _get_dynamic_rvol_threshold(
        bar_min, close, or_low, vwap, STRATEGY_ID, msa_confirmed=True)
    if rvol < rvol_min:
        logger.debug("[%s] MID_BRK: RVOL %.2f < %.1f — skipped", ticker, rvol, rvol_min)
        return None

    # Gate 6b: RVOL ceiling (off by default — see RVOL_CEILING docstring above)
    if RVOL_CEILING is not None and rvol > RVOL_CEILING:
        logger.debug("[%s] MID_BRK: RVOL %.2f > ceiling %.1f — likely exhaustion spike, skipped",
                     ticker, rvol, RVOL_CEILING)
        return None

    trend       = msa.classify_trend()
    trend_bonus = 0.05 if trend == "downtrend" else 0.0
    breakdown_pct = (or_low - close) / or_low
    mag_bonus     = min(0.04, breakdown_pct * 5)
    # REVERTED 2026-07-17: a 0.65->0.72 base-confidence bump (hypothesis: the
    # router's 0.74 floor was killing good signals) falsified TREND_CONT's
    # backtest (-$39.59 expectancy vs +$41 before), so reverted here too.
    confidence    = min(0.86, 0.65 + min(rvol - 1.0, 2.0) * 0.04 + trend_bonus + mag_bonus)

    # ── Structural stop (2026-07-21, research-backed) ─────────────────────
    # A confirmation entry (3 checks already true before entry) pairs with a
    # TIGHT stop just beyond the confirming pivot, not a wide ATR fallback —
    # this signal never carried entry_bar_high before, so every trade fell
    # back to the lagging ATR stop (audit's #1 loss reason, pre-2026-07-21).
    # STRUCT_STOP_MODE picks the level — see constant docstring above.
    if STRUCT_STOP_MODE == "pivot":
        _struct_ref = msa.last_swing_high()
    elif STRUCT_STOP_MODE == "prior_swing":
        _struct_ref = msa.prev_swing_high()
    elif STRUCT_STOP_MODE == "entry_bar":
        _struct_ref = float(last_bar["high"])
    else:   # "none"
        _struct_ref = None

    logger.info("[%s] MID_BRK bearish close=%.2f or_low=%.2f RVOL=%.2f trend=%s conf=%.2f",
                ticker, close, or_low, rvol, trend, confidence)
    return Signal(
        strategy_id = STRATEGY_ID,
        direction   = "bearish",
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "or_low":         or_low,
            "or_high":        or_high,
            "vwap":           vwap,
            "trend":          trend,
            "lh_confirmed":   True,
            "breakdown_pct":  round(breakdown_pct * 100, 2),
            "rvol_gate":        round(rvol_min, 2),
            "rvol_gate_reason": _rvol_threshold_reason(
                bar_min, close, or_low, vwap, STRATEGY_ID, msa_confirmed=True),
            # Structural stop — consumed by risk.structural_stop_from_level()
            # in both backtester.py and trading/entry.py (same meta key, same
            # code path live trading already uses for INST_ORB/VWAP_PB/CHAN_BREAK).
            "entry_bar_high": _struct_ref,
        },
    )
