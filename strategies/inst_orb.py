"""
strategies/inst_orb.py — Institutional Opening Range Breakout (INST_ORB)

Session window : 09:45 – 10:30 ET (extended to 10:45 for retest entries)

Entry logic — RETEST SEQUENCE (not raw breakout):
  Phase 1 — BREAKOUT DETECTED: first bar that closes outside the OR boundary.
             We do NOT enter here. We wait.
  Phase 2 — RETEST IN PROGRESS: price pulls back and the candle's low (bullish)
             or high (bearish) touches the OR boundary ± tolerance. The option
             premium has also pulled back from its peak, giving a better fill.
  Phase 3 — BOUNCE CONFIRMED: after touching the OR level, price closes back
             through it. This bar is the entry — direction is structurally
             confirmed, stop is just below the OR level, entry is tighter.

Why retest entry vs raw breakout:
  • Raw breakout entry is at the top of the initial surge — option premium peak.
  • Retest entry is at the OR level itself — cheaper premium, tighter stop.
  • The bounce bar confirms the OR flipped from resistance → support (or vice
    versa). That structural confirmation is the edge.

State machine (per ticker per day):
  idle → breakout_seen → retesting → (entry fires) → idle
  Resets daily. Failed retest (close back through in wrong direction) → idle.

Fixes vs. original raw-breakout INST_ORB
──────────────────────────────────────────
1. Retest state machine replaces immediate breakout entry
2. Per-ticker cooldown  — 20-min window blocks re-entry spam
3. MFE overextension gate still applies to the RETEST bar (not the breakout bar)
4. VWAP direction gate applies at the retest entry bar
5. Flip/fade signals: still supported — the breakout bar is the fade trigger;
   the retest is price coming back to test the failed level
"""

from __future__ import annotations

import logging
from datetime import date as _date
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

# Session window — breakout must be detected by 10:30; retest can complete by 10:45
_SESSION_START      = 9  * 60 + 45   # 09:45 — breakout detection window start
_BREAKOUT_DEADLINE  = 10 * 60 + 30   # 10:30 — breakout must be seen before this
_SESSION_END        = 10 * 60 + 45   # 10:45 — retest entry deadline

# Retest tolerance: how close price must come to the OR boundary to count as a retest.
# 0.15% of the boundary price, minimum $0.05. On SPY (~$730) this is ~$1.10.
# Prevents a "close enough" touch on a fast move from triggering too early.
_RETEST_TOLERANCE_PCT = 0.0015   # 0.15% of boundary price
_RETEST_TOLERANCE_MIN = 0.05     # absolute floor

# Per-ticker, per-day retest state machine.
# Key: (ticker, date_str)  Value: phase dict
_retest_state: dict[tuple[str, str], dict] = {}


def _get_state(ticker: str, today_date: _date) -> dict:
    """Return (and lazily initialize) the retest state for ticker+date."""
    key = (ticker, today_date.isoformat())
    if key not in _retest_state:
        _retest_state[key] = {
            "phase":       "idle",      # idle | breakout_seen | retesting
            "direction":   None,        # "bullish" | "bearish"
            "or_boundary": None,        # the OR level price must retest
            "breakout_bar":None,        # timestamp of the breakout bar (for logging)
            "retest_bar":  None,        # timestamp of the retest touch bar
        }
    # Prune stale state from prior days (keep only today + yesterday)
    stale = [k for k in _retest_state if k[1] < today_date.isoformat()]
    for k in stale:
        del _retest_state[k]
    return _retest_state[key]


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    """
    Evaluate INST_ORB signals via the retest entry state machine.

    Called once per tick with today's bars up to the current bar. Processes
    all bars in chronological order and advances the state machine. Returns
    a Signal only on the BOUNCE CONFIRMED bar (Phase 3).

    IMPORTANT — stateless-per-call design:
      The state machine is RESET at the start of every call and re-derived
      from scratch by replaying the bar slice in order. This is required for
      correct backtester behavior (called with growing slices on every bar).
      In live trading it is equivalent — the replay is cheap (< 78 5-min bars
      per session day) and produces identical results to accumulated state.

    Parameters
    ----------
    today  : DataFrame with columns time, open, high, low, close, volume, rvol, vwap, atr
    ticker : symbol — cooldown keying and log context
    """
    if len(today) < 2:
        return None

    or_data = get_opening_range(today)
    if or_data is None:
        return None
    or_high = or_data.get("high")
    or_low  = or_data.get("low")
    if or_high is None or or_low is None:
        return None

    today_date = today["time"].iloc[-1].date()

    # Reset state to idle on EVERY call so the state machine is re-derived
    # cleanly from the full bar slice. This prevents stale phase leftovers
    # from a prior call (same bar position, different slice length) corrupting
    # the phase transitions — the root cause of the backtester "no trades" bug.
    key = (ticker, today_date.isoformat())
    _retest_state[key] = {
        "phase":        "idle",
        "direction":    None,
        "or_boundary":  None,
        "breakout_bar": None,
        "retest_bar":   None,
    }
    # Prune stale state from prior days (cosmetic — prevents unbounded dict growth)
    stale = [k for k in list(_retest_state) if k[1] < today_date.isoformat()]
    for k in stale:
        del _retest_state[k]

    state = _retest_state[key]

    msa   = MarketStructureAnalyzer(today)
    trend = msa.classify_trend()

    result: Optional[Signal] = None

    for _, bar in today.iterrows():
        bar_time = bar["time"]
        if not isinstance(bar_time, pd.Timestamp):
            bar_time = pd.Timestamp(bar_time)
        bar_min = bar_time.hour * 60 + bar_time.minute

        # Gate: only evaluate inside the combined session window
        if not (_SESSION_START <= bar_min <= _SESSION_END):
            continue

        close  = float(bar["close"])
        low    = float(bar["low"])
        high   = float(bar["high"])
        volume = float(bar.get("volume", 0))
        rvol   = float(bar.get("rvol", 0.0))
        _vwap  = bar.get("vwap")
        vwap   = float(_vwap) if (_vwap is not None and not (isinstance(_vwap, float) and np.isnan(_vwap))) else None
        _atr   = bar.get("atr")
        atr    = float(_atr) if (_atr is not None and not (isinstance(_atr, float) and np.isnan(_atr))) else None

        if atr is None or atr <= 0:
            continue

        # ── PHASE TRANSITIONS ────────────────────────────────────────────────

        if state["phase"] == "idle":
            # Can only detect a new breakout before the deadline
            if bar_min > _BREAKOUT_DEADLINE:
                continue

            broke_high = close > or_high
            broke_low  = close < or_low
            if not broke_high and not broke_low:
                continue

            # Determine direction (with flip logic)
            if broke_high:
                direction = "bullish" if trend in ("uptrend", "consolidation") else "bearish"
            else:
                direction = "bearish" if trend in ("downtrend", "consolidation") else "bullish"

            # Record the breakout; do NOT enter — advance state to "wait for retest"
            state["phase"]        = "breakout_seen"
            state["direction"]    = direction
            state["or_boundary"]  = or_high if broke_high else or_low
            state["breakout_bar"] = bar_time
            state["retest_bar"]   = None
            logger.info(
                "[%s] INST_ORB breakout detected at %s — direction=%s boundary=%.2f. "
                "Waiting for retest before entry.",
                ticker, bar_time.strftime("%H:%M"), direction, state["or_boundary"],
            )
            continue  # don't enter on the breakout bar itself

        elif state["phase"] == "breakout_seen":
            # Look for the retest: price must come back and TOUCH the OR boundary.
            # For bullish: the candle's LOW must dip to/below the OR high (now support).
            # For bearish: the candle's HIGH must rise to/above the OR low (now resistance).
            boundary  = state["or_boundary"]
            tolerance = max(_RETEST_TOLERANCE_MIN, boundary * _RETEST_TOLERANCE_PCT)

            if state["direction"] == "bullish":
                touched = low <= boundary + tolerance
            else:
                touched = high >= boundary - tolerance

            if touched:
                state["phase"]     = "retesting"
                state["retest_bar"] = bar_time
                logger.info(
                    "[%s] INST_ORB retest touch at %s — low=%.2f high=%.2f boundary=%.2f. "
                    "Waiting for bounce confirmation.",
                    ticker, bar_time.strftime("%H:%M"), low, high, boundary,
                )
            else:
                # If price broke hard in the original direction with no retest
                # (e.g., close moved 2+ ATRs past the level), the retest window expired.
                boundary  = state["or_boundary"]
                if state["direction"] == "bullish" and close < boundary - atr:
                    logger.info("[%s] INST_ORB retest window failed — price broke back below OR. Resetting.", ticker)
                    state["phase"] = "idle"
                elif state["direction"] == "bearish" and close > boundary + atr:
                    logger.info("[%s] INST_ORB retest window failed — price broke back above OR. Resetting.", ticker)
                    state["phase"] = "idle"
            continue

        elif state["phase"] == "retesting":
            # Look for the bounce: after touching the OR boundary, price closes
            # back through it. THIS is the entry bar.
            boundary  = state["or_boundary"]
            direction = state["direction"]

            bounce_confirmed = (
                (direction == "bullish" and close > boundary) or
                (direction == "bearish" and close < boundary)
            )

            if not bounce_confirmed:
                # Still testing — if price closes firmly the wrong way, reset
                if direction == "bullish" and close < boundary - atr:
                    logger.info("[%s] INST_ORB bounce failed (close %.2f < boundary %.2f - ATR %.2f). Resetting.", ticker, close, boundary, atr)
                    state["phase"] = "idle"
                elif direction == "bearish" and close > boundary + atr:
                    logger.info("[%s] INST_ORB bounce failed (close %.2f > boundary %.2f + ATR %.2f). Resetting.", ticker, close, boundary, atr)
                    state["phase"] = "idle"
                continue

            # Bounce confirmed — apply entry gates before building signal

            # Gate: cooldown
            if check_cooldown(STRATEGY_ID, ticker, bar_time):
                logger.debug("[%s] INST_ORB retest entry skipped — cooldown active", ticker)
                state["phase"] = "idle"
                continue

            # Gate: don't enter if price is now overextended past the boundary.
            # Raised from 1.5 → 3.0 ATR: a bounce of 2-3 ATRs from the OR level
            # is momentum confirmation, not overextension. The old threshold was
            # blocking clean ORB trades (e.g. SPY 2.35 ATR bounce → skipped, then
            # ran +$7). Overextension only becomes a concern at 3+ ATRs out.
            dist_from_boundary = abs(close - boundary)
            if dist_from_boundary > 3.0 * atr:
                logger.info(
                    "[%s] INST_ORB retest entry skipped — bounce ran too far "
                    "(%.2f ATRs from boundary). Skip this bar.",
                    ticker, dist_from_boundary / atr,
                )
                state["phase"] = "idle"
                continue

            # Gate: RVOL
            rvol_threshold = _get_dynamic_rvol_threshold(
                bar_min=bar_min, close=close, or_low=or_low, vwap=vwap, strategy_id=STRATEGY_ID,
            )
            rvol_reason = _rvol_threshold_reason(
                bar_min=bar_min, close=close, or_low=or_low, vwap=vwap, strategy_id=STRATEGY_ID,
            )
            if rvol < rvol_threshold:
                logger.debug("[%s] INST_ORB retest RVOL gate: %.2f < %.2f (%s)", ticker, rvol, rvol_threshold, rvol_reason)
                state["phase"] = "idle"
                continue

            # Gate: VWAP trend direction (dead-cat-bounce protection)
            # The static VWAP level gate is bypassed — during a retest, price
            # is naturally at the OR boundary which is often below VWAP. But the
            # VWAP SLOPE since the breakout is the real signal: if VWAP is declining
            # since the breakout bar, institutional order flow is bearish and a
            # bullish ORB call is a dead-cat bounce. Vice versa for bearish fades.
            if vwap is not None and state["breakout_bar"] is not None:
                # Find VWAP value at the time of the breakout bar
                _bb_rows = today[today["time"] == state["breakout_bar"]]
                _vwap_at_breakout = float(_bb_rows.iloc[0].get("vwap", vwap)) if not _bb_rows.empty else vwap

                # 0.03% VWAP change since breakout = institutional flow direction
                _vwap_drift = (vwap - _vwap_at_breakout) / max(_vwap_at_breakout, 1.0)

                if direction == "bullish" and _vwap_drift < -0.0003:
                    logger.info(
                        "[%s] INST_ORB: bullish entry blocked — VWAP declined %.3f%% since breakout "
                        "(%.2f→%.2f) — dead-cat-bounce pattern, skipping call.",
                        ticker, _vwap_drift * 100, _vwap_at_breakout, vwap,
                    )
                    state["phase"] = "idle"
                    continue

                if direction == "bearish" and _vwap_drift > 0.0003:
                    logger.info(
                        "[%s] INST_ORB: bearish entry blocked — VWAP rose %.3f%% since breakout "
                        "(%.2f→%.2f) — breakout is real, not a fade opportunity.",
                        ticker, _vwap_drift * 100, _vwap_at_breakout, vwap,
                    )
                    state["phase"] = "idle"
                    continue

                logger.debug(
                    "[%s] INST_ORB retest — VWAP drift since breakout: %.3f%% (breakout=%.2f now=%.2f) — OK",
                    ticker, _vwap_drift * 100, _vwap_at_breakout, vwap,
                )

            # All gates passed — build signal
            confidence = _compute_confidence(
                rvol=rvol, rvol_threshold=rvol_threshold, atr=atr, close=close,
                or_high=or_high, or_low=or_low, direction=direction,
                direction_flipped=(
                    (direction == "bearish" and close > or_high) or
                    (direction == "bullish" and close < or_low)
                ),
                trend=trend,
                is_retest=True,   # retest entries get a confidence bonus
            )

            register_cooldown(STRATEGY_ID, ticker, bar_time)
            state["phase"] = "idle"  # reset so we don't fire twice

            logger.info(
                "[%s] INST_ORB RETEST ENTRY at %s — direction=%s boundary=%.2f "
                "close=%.2f confidence=%.2f rvol=%.2f trend=%s "
                "(breakout at %s, retest touch at %s)",
                ticker, bar_time.strftime("%H:%M"), direction, boundary, close,
                confidence, rvol, trend,
                state["breakout_bar"].strftime("%H:%M") if state["breakout_bar"] else "?",
                state["retest_bar"].strftime("%H:%M")   if state["retest_bar"]   else "?",
            )

            # For structural stop calculation at entry:
            # CALL (bullish): structural stop on the underlying = the retest low
            #   (if price breaks back below the OR level, the thesis is wrong)
            # PUT (bearish): structural stop on the underlying = the retest high
            _entry_bar_low  = float(bar["low"])  if direction == "bullish" else None
            _entry_bar_high = float(bar["high"]) if direction == "bearish" else None

            result = Signal(
                confidence  = confidence,
                strategy_id = STRATEGY_ID,
                direction   = direction,
                rvol        = rvol,
                trigger_bar = bar_time,
                meta        = {
                    "or_high"          : or_high,
                    "or_low"           : or_low,
                    "or_boundary"      : boundary,
                    "atr"              : atr,
                    "vwap"             : vwap,
                    "trend"            : trend,
                    "entry_type"       : "retest",
                    "breakout_bar"     : str(state["breakout_bar"]),
                    "retest_bar"       : str(state["retest_bar"]),
                    "rvol_threshold"   : rvol_threshold,
                    "rvol_reason"      : rvol_reason,
                    # Structural stop levels — passed to risk.structural_stop_from_level()
                    # at entry so the position is protected by chart structure, not %
                    "entry_bar_low"    : _entry_bar_low,
                    "entry_bar_high"   : _entry_bar_high,
                },
            )
            # Don't break — keep iterating; the last qualifying signal wins (most recent bar)

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
    is_retest: bool = False,
) -> float:
    """
    0–1 confidence score.
    Components:
      35% — RVOL strength relative to threshold
      25% — proximity to OR boundary (retest entries start closer → higher score)
      20% — trend alignment (confirmed > consolidation > counter-trend)
      10% — flip quality penalty (flipped signals get a haircut)
      10% — retest bonus (retest entries are higher probability than raw breakouts)
    """
    # Score RVOL as excess above threshold, scaled so 2× threshold = full score.
    # Previous /3.0 divisor made rvol_score=0.42 even at 1.5× — too stingy.
    # New formula: threshold = 0, 2× threshold = 1.0. Linear in between.
    rvol_excess = max(rvol - rvol_threshold, 0.0)
    rvol_score  = min(rvol_excess / max(rvol_threshold, 0.01), 1.0)

    boundary   = or_high if direction == "bullish" else or_low
    dist_atrs  = abs(close - boundary) / atr
    # Retest entries should be very close to the boundary (0–0.5 ATR)
    # Raw breakout entries were 0–2 ATR. Tighter scale for retest.
    prox_score = max(0.0, 1.0 - dist_atrs / (1.0 if is_retest else 2.0))

    if direction == "bullish":
        trend_score = 1.0 if trend == "uptrend" else (0.6 if trend == "consolidation" else 0.3)
    else:
        trend_score = 1.0 if trend == "downtrend" else (0.6 if trend == "consolidation" else 0.3)

    flip_multiplier  = 0.85 if direction_flipped else 1.0
    retest_bonus     = 0.10 if is_retest else 0.0

    confidence = (0.35 * rvol_score + 0.25 * prox_score + 0.20 * trend_score + 0.10 + retest_bonus) * flip_multiplier
    return round(min(confidence, 1.0), 4)
