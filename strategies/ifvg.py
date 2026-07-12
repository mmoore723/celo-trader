"""
strategies/ifvg.py — Inverted Fair Value Gap (IFVG)

ICT concept: when a standard 3-candle FVG is fully mitigated (price body-closes
through the far edge of the gap), the zone flips polarity — a bullish imbalance
becomes resistance; a bearish imbalance becomes support.  Entry fires when price
comes back to RETEST the inverted zone.

Signal direction is OPPOSITE to the original gap:
  Bullish FVG fully violated  → IFVG zone = resistance → BEARISH signal (puts)
  Bearish FVG fully violated  → IFVG zone = support    → BULLISH signal (calls)

Hard gates (all must pass):
  1. Liquidity sweep REQUIRED before the original gap formed — unlike FVG where
     it's a confidence bonus, here it is a hard blocker.  Without a sweep the
     zone flip is just price noise, not an institutional reversal.
  2. Full candle BODY close through the far edge (not a wick poke).
  3. Retest of the inverted zone within _RETEST_MAX_BARS bars of the violation.
  4. Original gap formed within the last _GAP_LOOKBACK bars.
  5. RVOL ≥ 1.5 on the retest bar (volume confirms the retest).
  6. VWAP soft gate — conflict reduces confidence -0.05 but does not block.
  7. Each inverted zone fires at most once per session.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, MarketStructureAnalyzer
from strategies.fvg import _detect_liquidity_sweep   # reuse ICT sweep detector

logger = logging.getLogger("celo_trader.strategies.ifvg")

STRATEGY_ID = "IFVG"

# Session-scoped deduplication set — keyed separately from FVG's set so both
# strategies can coexist on the same underlying zone without interfering.
_consumed_ifvgs: set[tuple] = set()

_GAP_LOOKBACK    = 25   # max bars back to look for original gap
_RETEST_MAX_BARS = 15   # retest must happen within this many bars of violation


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    """
    Scan for inverted FVG setups on the current bar.

    Works by iterating over the same 3-candle pattern as FVG, then checking:
      (a) Was the gap subsequently fully violated?  (body close through far edge)
      (b) Is the current bar retesting the inverted zone from the opposite side?
      (c) Are all hard gates satisfied?

    Returns a Signal if a setup qualifies, None otherwise.
    """
    if len(today) < 8:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Need session history for reliable zone flip detection
    if bar_min < 9 * 60 + 45:
        return None

    c_close = float(last_bar["close"])
    c_rvol  = float(last_bar["rvol"])  if not pd.isna(last_bar.get("rvol",  np.nan)) else 0.0
    c_vwap  = float(last_bar["vwap"])  if not pd.isna(last_bar.get("vwap",  np.nan)) else None
    atr     = float(last_bar["atr"])   if not pd.isna(last_bar.get("atr",   np.nan)) else 0.0

    msa       = MarketStructureAnalyzer(today)
    n         = len(today)
    look_back = min(_GAP_LOOKBACK, n - 3)   # need ≥3 bars after the gap

    for k in range(look_back, 0, -1):
        if k - 1 < 0 or k + 1 >= n:
            continue

        b_prev = today.iloc[k - 1]
        b_next = today.iloc[k + 1]

        gap_low   = None
        gap_high  = None
        direction = None

        # ── Identify original 3-candle FVG pattern ───────────────────────────
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
            continue   # too thin to matter

        # ── Gate 1: Liquidity sweep REQUIRED ─────────────────────────────────
        # Must exist before or around the gap formation.  We check here rather
        # than after violation to avoid scanning sweep on zones that have no sweep.
        sweep_detected = _detect_liquidity_sweep(today, direction, msa)
        if not sweep_detected:
            logger.debug(
                "[%s] IFVG: no sweep for %s gap [%.4f–%.4f] — skipped (required)",
                ticker, direction, gap_low, gap_high,
            )
            continue

        # ── Gate 2: Full body close through far edge (violation) ─────────────
        # Scan bars after the gap (k+2 onward) for a candle that body-closed
        # completely past the gap's far edge.  We take the FIRST such violation.
        violated          = False
        violation_bar_idx = None

        for j in range(k + 2, n - 1):   # bars after gap, excluding current
            bar_j_close = float(today.iloc[j]["close"])
            if direction == "bullish":
                # Bullish gap violated when body closes BELOW gap_low
                if bar_j_close < gap_low:
                    violated          = True
                    violation_bar_idx = j
                    break
            else:
                # Bearish gap violated when body closes ABOVE gap_high
                if bar_j_close > gap_high:
                    violated          = True
                    violation_bar_idx = j
                    break

        if not violated or violation_bar_idx is None:
            continue

        # ── Gate 3: Current bar must be retesting the inverted zone ──────────
        if not (gap_low <= c_close <= gap_high):
            continue

        # ── Gate 4: Retest must be within _RETEST_MAX_BARS of violation ──────
        bars_since_violation = (n - 1) - violation_bar_idx
        if bars_since_violation < 1:
            continue   # current bar can't be the violation bar itself
        if bars_since_violation > _RETEST_MAX_BARS:
            logger.debug(
                "[%s] IFVG %s: retest too late (%d bars since violation, max %d) — skipped",
                ticker, direction, bars_since_violation, _RETEST_MAX_BARS,
            )
            continue

        # ── Gate 5: RVOL ≥ 1.5 on retest bar ────────────────────────────────
        if c_rvol < 1.5:
            logger.debug(
                "[%s] IFVG: RVOL %.2f < 1.5 on retest — skipped", ticker, c_rvol,
            )
            continue

        # ── Signal direction (opposite of original gap) ───────────────────────
        new_direction = "bearish" if direction == "bullish" else "bullish"

        # ── Gate 6: VWAP soft gate ────────────────────────────────────────────
        # Conflict reduces confidence -0.05 but does not block — the zone flip
        # itself is primary confluence; VWAP is a secondary quality signal.
        vwap_aligned = True
        if c_vwap is not None:
            if new_direction == "bullish" and c_close < c_vwap:
                vwap_aligned = False
            elif new_direction == "bearish" and c_close > c_vwap:
                vwap_aligned = False

        # ── Gate 7: Deduplication ─────────────────────────────────────────────
        today_str = str(bar_time.date()) if hasattr(bar_time, "date") else str(bar_time)[:10]
        _gap_key  = (ticker, today_str, round(gap_low, 4), round(gap_high, 4), "ifvg")
        if _gap_key in _consumed_ifvgs:
            logger.debug(
                "[%s] IFVG %s: zone [%.4f–%.4f] already consumed — skipped",
                ticker, new_direction, gap_low, gap_high,
            )
            continue

        # ── Confidence ────────────────────────────────────────────────────────
        # Base: sweep confirmed + zone flipped + retest = institutional reversal.
        # Bonus: large gap relative to ATR, higher RVOL.
        # Penalty: VWAP conflict.
        gap_ratio  = gap_width / atr if atr > 0 else 1.0
        confidence = (
            0.60
            + min(gap_ratio, 2.0) * 0.08          # bigger gap = stronger flip
            + min(c_rvol - 1.5, 1.0) * 0.05       # volume quality bonus
            + (0.0 if vwap_aligned else -0.05)     # VWAP conflict penalty
        )
        confidence = round(min(0.88, max(0.55, confidence)), 4)

        logger.info(
            "[%s] IFVG %s signal: original=%s gap=[%.4f–%.4f] violated @bar %d "
            "(%d bars ago) RVOL=%.2f conf=%.2f vwap_aligned=%s",
            ticker, new_direction, direction, gap_low, gap_high,
            violation_bar_idx, bars_since_violation, c_rvol, confidence, vwap_aligned,
        )

        # Mark consumed and purge stale (previous day) entries
        _consumed_ifvgs.add(_gap_key)
        _stale = {kk for kk in _consumed_ifvgs
                  if isinstance(kk, tuple) and len(kk) >= 2 and kk[1] < today_str}
        _consumed_ifvgs.difference_update(_stale)

        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = new_direction,
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "original_direction":   direction,
                "gap_low":              gap_low,
                "gap_high":             gap_high,
                "gap_width":            gap_width,
                "atr":                  atr,
                "vwap":                 c_vwap,
                "violation_bar_idx":    violation_bar_idx,
                "bars_since_violation": bars_since_violation,
                "vwap_aligned":         vwap_aligned,
            },
        )

    return None
