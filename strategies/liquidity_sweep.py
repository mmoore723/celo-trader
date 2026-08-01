"""
strategies/liquidity_sweep.py — Liquidity Sweep Reversal (LIQ_SWEEP)

Session: 09:45-15:30 ET | Direction: opposite the wick (fades the sweep)

Added 2026-07-31 per explicit user request, after a chart review where NVDA
wicked through a level and reversed hard — a pattern no strategy in this
bot traded (every other strategy trades WITH a breakout, not against a
failed one). Researched against 10+ outside sources on liquidity sweeps /
stop hunts / false-breakout fades before building.

Entry logic — fade a failed breakout, not a real one:
  A "sweep" is a bar whose wick pierces a recent swing high/low (the SAME
  MarketStructureAnalyzer swing detector every other strategy here uses —
  not a second swing definition) by a meaningful amount, but then CLOSES
  back on the other side of that level. That close-back-in bar is the
  entry, faded in the OPPOSITE direction of the wick:
    - High sweep, closes back below it → fade DOWN (put)
    - Low sweep,  closes back above it → fade UP (call)
  Gate order:
    1. Session window: 09:45-15:30 ET (skips the noisy open + closing drive)
    2. A real swing level exists to sweep
    3. Wick penetration past the level >= 0.15 ATR — filters single-tick
       noise, same threshold MSA itself uses to admit a pivot
    4. Close-back rejection >= 0.10 ATR past the level — a real reversal,
       not a graze
    5. RVOL confirms real participation on the stab (dynamic threshold,
       same helper every other strategy uses)
  Stop reference: the wick extreme itself — if price retakes it, the sweep
  thesis (this was a trap, not a real move) is wrong. Padded an ADDITIONAL
  0.5×ATR beyond the wick (2026-07-31, corrected same-day — see stop_ref
  below for why the first version of this fix was a no-op) so normal
  post-sweep chop doesn't clip the trade before the thesis has room to play out.

UNTESTED — see api/models.py's liquidity_sweep_enabled comment. Built from
published sources, not yet validated against this bot's own backtester.
Run a backtest before trusting live sizing.
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

logger = logging.getLogger("celo_trader.strategies.liquidity_sweep")

STRATEGY_ID = "LIQ_SWEEP"

_SESSION_START_MIN = 9 * 60 + 45    # 09:45 ET — skip the noisy open
_SESSION_END_MIN   = 15 * 60 + 30   # 15:30 ET — skip the closing drive

_PENETRATION_ATR_MIN = 0.15   # wick must clear the level by this many ATRs
_REJECTION_ATR_MIN   = 0.10   # close must come back past the level by this many ATRs


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 8:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    if not (_SESSION_START_MIN <= bar_min <= _SESSION_END_MIN):
        return None

    if check_cooldown(STRATEGY_ID, ticker, bar_time):
        return None

    _atr = last_bar.get("atr")
    atr  = float(_atr) if (_atr is not None and not (isinstance(_atr, float) and np.isnan(_atr))) else None
    if atr is None or atr <= 0:
        return None

    # Swing levels from the SAME detector every other strategy uses — built
    # from everything up to (but not including) this bar, so the bar being
    # tested can't be counted as its own swing pivot.
    msa        = MarketStructureAnalyzer(today.iloc[:-1])
    swing_high = msa.last_swing_high()
    swing_low  = msa.last_swing_low()

    high  = float(last_bar["high"])
    low   = float(last_bar["low"])
    close = float(last_bar["close"])
    rvol  = float(last_bar["rvol"]) if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0

    direction: Optional[str] = None
    swept_level: Optional[float] = None
    wick_extreme: Optional[float] = None

    # High sweep → fade DOWN
    if swing_high is not None and high > swing_high + _PENETRATION_ATR_MIN * atr:
        if close < swing_high - _REJECTION_ATR_MIN * atr:
            direction, swept_level, wick_extreme = "bearish", swing_high, high

    # Low sweep → fade UP (only checked if the high-sweep case didn't already fire)
    if direction is None and swing_low is not None and low < swing_low - _PENETRATION_ATR_MIN * atr:
        if close > swing_low + _REJECTION_ATR_MIN * atr:
            direction, swept_level, wick_extreme = "bullish", swing_low, low

    if direction is None:
        return None

    # RVOL gate — a sweep with no real volume behind it reads as noise, not
    # a genuine stop-hunt with size behind the reversal.
    rvol_min = _get_dynamic_rvol_threshold(bar_min, close, None, None, STRATEGY_ID, msa_confirmed=False)
    if rvol < rvol_min:
        logger.debug("[%s] LIQ_SWEEP: RVOL %.2f < %.2f — skipped", ticker, rvol, rvol_min)
        return None

    penetration_atrs = abs((high if direction == "bearish" else low) - swept_level) / atr
    rejection_atrs   = abs(close - swept_level) / atr

    # Confidence: rejection strength matters more than penetration depth — a
    # deep wick with a weak close-back is still an open trade, not a
    # confirmed reversal. Capped below every backtested strategy's ceiling.
    rejection_score    = min(rejection_atrs, 1.0)
    penetration_score  = min(penetration_atrs, 1.0)
    rvol_score         = min(max(rvol - rvol_min, 0.0) / max(rvol_min, 0.01), 1.0)
    confidence = min(0.82, 0.60 + 0.15 * rejection_score + 0.05 * penetration_score + 0.10 * rvol_score)

    # Structural stop — the wick extreme itself is the correct INVALIDATION
    # level (if price retakes it, the sweep thesis is wrong), but handing it
    # to the exit engine with zero padding produced a near-zero-width stop in
    # practice: real backtested distance (penetration + rejection) averaged
    # only 1.31 ATR, which the 0.40-delta option-price conversion compresses
    # into a razor-thin premium move (2026-07-31 audit: 20/21 trades stopped
    # out via this exact path, avg hold 4.2 min).
    #
    # BUG (2026-07-31, first attempt): this was originally written as
    # max(wick_extreme, close ± 0.5×ATR) — a FLOOR, copying chan_break.py's
    # pattern. That works for chan_break because its reference (prev bar's
    # high/low) can be near-zero distance from entry. LIQ_SWEEP's entry gate
    # already guarantees the wick is >= ~0.25 ATR away (avg 1.31 ATR in real
    # trades) — always further than the 0.5×ATR floor, so max() always kept
    # the original wick and the "fix" never activated. Confirmed by rerunning
    # the backtest: P&L came back byte-for-byte identical to the pre-fix run.
    # Corrected to ADD 0.5×ATR beyond the wick instead of flooring at it, so
    # it always widens the stop regardless of how far the wick already is.
    if direction == "bearish":
        stop_ref = wick_extreme + 0.5 * atr
    else:
        stop_ref = wick_extreme - 0.5 * atr

    register_cooldown(STRATEGY_ID, ticker, bar_time)
    logger.info(
        "[%s] LIQ_SWEEP %s — swept %.2f, wick to %.2f (%.2f ATR), closed %.2f (%.2f ATR rejection), "
        "stop_ref=%.2f, RVOL=%.2f conf=%.2f",
        ticker, direction, swept_level, wick_extreme, penetration_atrs, close, rejection_atrs, stop_ref, rvol, confidence,
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
            "rvol_gate_reason": _rvol_threshold_reason(bar_min, close, None, None, STRATEGY_ID, msa_confirmed=False),
            # Structural stop — wick extreme, floored at 0.5×ATR beyond entry
            # (same meta key convention risk.structural_stop_from_level() already
            # reads; same 0.5×ATR floor pattern as chan_break.py's entry_bar_high/low).
            "entry_bar_high": round(stop_ref, 4) if direction == "bearish" else None,
            "entry_bar_low":  round(stop_ref, 4) if direction == "bullish" else None,
        },
    )
