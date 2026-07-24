"""
strategies/gap_go.py — Gap and Go (GAP_GO)

Session: 09:30–09:45 ET | Direction: matches the gap (up=bullish, down=bearish)

Added 2026-07-23 (Gap 2, professional-strategy-alignment audit): one of the
most widely published day-trading archetypes — trade the continuation of a
pre-market gap in the first minutes after the open — had no representative
strategy in this bot. INST_ORB starts at 09:45, after the classic gap-and-go
window has already closed, so this isn't a duplicate of it.

Entry logic — momentum continuation, not raw gap presence:
  A stock merely gapping isn't tradeable on its own; professionals require
  the gap to be DEFENDED in the first few minutes (price extending further
  in the gap direction, not immediately fading to fill it). Gate order:
    1. Session window: 09:30-09:45 ET only
    2. Real gap: session_gap_pct clears scanner.py's own thresholds (same
       constants the ticker scanner already uses — single source of truth,
       not a second gap definition that could drift from the first)
    3. Continuation: current close beyond the opening bar's own high/low —
       price is still pushing past its own first print, not reversing
    4. RVOL confirms real participation (dynamic threshold, same helper
       every other strategy uses)
  Stop reference: the low (bullish) / high (bearish) since the open — if
  price trades back through where it opened, the gap has failed.

UNTESTED — default OFF (see strategy_gapgo_enabled in Settings). Built from
published sources, not yet validated against this bot's own backtester the
way every other strategy here has been. Run a backtest before enabling live.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import (
    Signal,
    _get_dynamic_rvol_threshold,
    _rvol_threshold_reason,
    check_cooldown,
    register_cooldown,
)
from scanner import _MIN_GAP_PCT, _MAX_GAP_PCT, _MIN_GAP_PCT_ETF, _ETF_SET

logger = logging.getLogger("celo_trader.strategies.gap_go")

STRATEGY_ID = "GAP_GO"

_SESSION_START_MIN = 9 * 60 + 30   # 09:30 ET — market open
_SESSION_END_MIN   = 9 * 60 + 45   # 09:45 ET — INST_ORB takes over from here


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 3:
        return None

    last_bar = today.iloc[-1]
    bar_time = last_bar["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    # Gate 1: session window — the classic gap-and-go minutes only
    if not (_SESSION_START_MIN <= bar_min <= _SESSION_END_MIN):
        return None

    if check_cooldown(STRATEGY_ID, ticker, bar_time):
        return None

    gap_pct = float(last_bar.get("session_gap_pct", 0.0))
    if pd.isna(gap_pct):
        return None
    direction = "bullish" if gap_pct > 0 else "bearish"
    abs_gap   = abs(gap_pct)

    # Gate 2: real gap — same thresholds scanner.py already uses to select
    # tickers, so a name that wouldn't even qualify for today's watchlist on
    # gap grounds can't fire this strategy through a different definition.
    _gap_min = _MIN_GAP_PCT_ETF if ticker in _ETF_SET else _MIN_GAP_PCT
    if not (_gap_min <= abs_gap <= _MAX_GAP_PCT):
        logger.debug("[%s] GAP_GO: gap %.2f%% outside [%.1f, %.1f] — skipped",
                     ticker, gap_pct, _gap_min, _MAX_GAP_PCT)
        return None

    open_bar   = today.iloc[0]
    open_high  = float(open_bar["high"])
    open_low   = float(open_bar["low"])
    close      = float(last_bar["close"])
    rvol       = float(last_bar["rvol"]) if not pd.isna(last_bar.get("rvol", np.nan)) else 0.0

    # Gate 3: continuation — price still pushing past its OWN opening bar,
    # not fading back into the gap. This is the "defended, not just present"
    # filter that separates gap-and-go from a gap that dies at the bell.
    if direction == "bullish" and close <= open_high:
        logger.debug("[%s] GAP_GO bullish: close %.2f hasn't cleared open-bar high %.2f — no continuation",
                     ticker, close, open_high)
        return None
    if direction == "bearish" and close >= open_low:
        logger.debug("[%s] GAP_GO bearish: close %.2f hasn't cleared open-bar low %.2f — no continuation",
                     ticker, close, open_low)
        return None

    # Gate 4: RVOL — same dynamic-threshold helper every other strategy uses
    rvol_min = _get_dynamic_rvol_threshold(bar_min, close, None, None, STRATEGY_ID, msa_confirmed=False)
    if rvol < rvol_min:
        logger.debug("[%s] GAP_GO: RVOL %.2f < %.1f — skipped", ticker, rvol, rvol_min)
        return None

    # Structural stop: the low/high since the open — if price trades back
    # through where it opened, the gap has failed and the trade thesis is gone.
    since_open = today
    struct_ref = (float(since_open["low"].min())  if direction == "bullish"
                  else float(since_open["high"].max()))

    gap_bonus = min(0.06, abs_gap * 0.02)
    confidence = min(0.84, 0.66 + min(rvol - rvol_min, 1.5) * 0.05 + gap_bonus)

    register_cooldown(STRATEGY_ID, ticker, bar_time)
    logger.info("[%s] GAP_GO %s gap=%.2f%% close=%.2f RVOL=%.2f conf=%.2f",
                ticker, direction, gap_pct, close, rvol, confidence)
    return Signal(
        strategy_id = STRATEGY_ID,
        direction   = direction,
        confidence  = confidence,
        rvol        = rvol,
        trigger_bar = bar_time,
        meta        = {
            "gap_pct":        round(gap_pct, 3),
            "open_high":      open_high,
            "open_low":       open_low,
            "rvol_gate":        round(rvol_min, 2),
            "rvol_gate_reason": _rvol_threshold_reason(bar_min, close, None, None, STRATEGY_ID, msa_confirmed=False),
            # Structural stop — same meta key every other strategy's stop-
            # placement code already reads (risk.structural_stop_from_level()).
            "entry_bar_high": struct_ref if direction == "bearish" else None,
            "entry_bar_low":  struct_ref if direction == "bullish" else None,
        },
    )
