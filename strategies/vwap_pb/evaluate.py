"""
strategies/vwap_pb/evaluate.py — evaluate(): VWAP Pullback (VWAP_PB) entry logic.

Trend-continuation pullback to VWAP:
  Bullish: EMA50 + VWAP both rising, price taps VWAP (within 0.2%) then reclaims.
  Bearish: EMA50 + VWAP both falling, price taps VWAP then rejects.

Entry gates (2026-07-15 rework after 10% WR audit):
  • 5-of-5 blowthrough guard  • 0.2% touch proximity  • VWAP slope
  • EMA50 slope  • ADX ≥ 25 regime (enforced in strategy_router)

Session: 09:45–EOD  (skips opening chaos)

Split out of the old single strategies/vwap_pb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. `evaluate()` is kept as ONE
function (irreducible-function exception) — its four nested closures
(_was_above_vwap, _was_below_vwap, _fast_recovery_bull, _fast_recovery_bear)
and the bullish/bearish condition blocks all close over shared outer-scope
locals (c_vwap, p_vwap, curr, c_close, _TOUCH_PCT, etc.), unlike
chan_break.py's genuinely independent bull/bear halves — splitting this
function would mean threading a dozen+ shared locals through extra
parameters for no real benefit and real risk of transcription error.

A/B-knob note: BLOWTHROUGH_MIN_BARS, FAST_RECOVERY_ENABLED,
FAST_RECOVERY_MIN_BODY_PCT, CANDLESTICK_FILTER_ENABLED,
CANDLESTICK_MIN_WICK_RATIO, MAX_PULLBACK_COUNT, and _PULLBACK_LOOKBACK are
read via a live dotted lookup on the package object (`_pkg.ATTR`) at the top
of evaluate(), NOT via `from strategies.vwap_pb.constants import ATTR`.
Archived diagnostic scripts (scripts/diagnostics/archive/ab_test_vwap_pb.py,
ab_test_candlestick_filter.py) monkey-patch these as
`vwap_pb.BLOWTHROUGH_MIN_BARS = 3` on the package object before calling
`vwap_pb.evaluate(...)`. A `from constants import ATTR` binding captured
once at module-load time would never see that later mutation (ints/bools
are rebound, not mutated in place, so the old and new bindings point to
different objects) — a live dotted lookup on the package each call
reproduces the original single-file module's exact semantics, where a bare
global name inside a function always resolves against its own module's
current namespace at call time.
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
)
from candlestick_patterns import is_hammer, is_shooting_star
from strategies.vwap_pb.constants import STRATEGY_ID
from strategies.vwap_pb.pullback import _count_prior_pullbacks

logger = logging.getLogger("celo_trader.strategies.vwap_pb")


def evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]:
    if len(today) < 8:
        return None

    # Live dotted lookup on the package namespace — see module docstring for
    # why this can't be a `from constants import ATTR` at the top of the file.
    import strategies.vwap_pb as _pkg
    BLOWTHROUGH_MIN_BARS       = _pkg.BLOWTHROUGH_MIN_BARS
    FAST_RECOVERY_ENABLED      = _pkg.FAST_RECOVERY_ENABLED
    FAST_RECOVERY_MIN_BODY_PCT = _pkg.FAST_RECOVERY_MIN_BODY_PCT
    CANDLESTICK_FILTER_ENABLED = _pkg.CANDLESTICK_FILTER_ENABLED
    CANDLESTICK_MIN_WICK_RATIO = _pkg.CANDLESTICK_MIN_WICK_RATIO
    MAX_PULLBACK_COUNT         = _pkg.MAX_PULLBACK_COUNT
    _PULLBACK_LOOKBACK         = _pkg._PULLBACK_LOOKBACK

    prev = today.iloc[-2]
    curr = today.iloc[-1]

    bar_time = curr["time"]
    if not isinstance(bar_time, pd.Timestamp):
        bar_time = pd.Timestamp(bar_time)
    bar_min = bar_time.hour * 60 + bar_time.minute

    if bar_min < 9 * 60 + 45:
        return None

    c_close = float(curr["close"])
    c_vwap  = float(curr["vwap"])  if not pd.isna(curr.get("vwap", np.nan)) else None
    c_rvol  = float(curr["rvol"])  if not pd.isna(curr.get("rvol", np.nan)) else 0.0
    c_ema50 = float(curr["ema50"]) if not pd.isna(curr.get("ema50", np.nan)) else c_close

    p_low  = float(prev["low"])
    p_high = float(prev["high"])
    p_vwap = float(prev["vwap"]) if not pd.isna(prev.get("vwap", np.nan)) else None

    if c_vwap is None or p_vwap is None:
        return None

    msa          = MarketStructureAnalyzer(today)
    msa_ok_bull  = msa.confirmed_higher_low()
    msa_ok_bear  = msa.confirmed_lower_high()

    # ── Blowthrough guard ──────────────────────────────────────────────────────
    # A true pullback needs price on the correct side of VWAP for BLOWTHROUGH_MIN_BARS
    # of the last 5 bars. Fewer opposing bars allowed = looser = catches more
    # setups but also more crash-through moves. See A/B knobs above.
    _lookback_bars = today.iloc[-6:-1] if len(today) >= 6 else today.iloc[:-1]

    def _was_above_vwap(bars: pd.DataFrame) -> bool:
        """True if >= BLOWTHROUGH_MIN_BARS of the last 5 bars closed above vwap."""
        if len(bars) < 5:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        _n_above = sum(float(c) > float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))
        return _n_above >= BLOWTHROUGH_MIN_BARS

    def _was_below_vwap(bars: pd.DataFrame) -> bool:
        """True if >= BLOWTHROUGH_MIN_BARS of the last 5 bars closed below vwap."""
        if len(bars) < 5:
            return False
        _closes = bars["close"].values
        _vwaps  = bars["vwap"].values if "vwap" in bars.columns else [c_vwap] * len(bars)
        _n_below = sum(float(c) < float(v) for c, v in zip(_closes, _vwaps) if not pd.isna(v))
        return _n_below >= BLOWTHROUGH_MIN_BARS

    def _fast_recovery_bull() -> bool:
        """
        Exception path: prev bar pierced meaningfully below VWAP, but current
        bar reclaimed with a strong-bodied candle (real momentum, not a
        1-tick wobble). Only used when FAST_RECOVERY_ENABLED is True.
        """
        if not FAST_RECOVERY_ENABLED:
            return False
        _pierced = p_low < p_vwap * (1.0 - _TOUCH_PCT)   # beyond the normal touch band
        _range = max(float(curr["high"]) - float(curr["low"]), 0.0001)
        _body  = abs(c_close - float(curr.get("open", c_close)))
        _strong_body = (_body / _range) > FAST_RECOVERY_MIN_BODY_PCT
        return _pierced and c_close > c_vwap and _strong_body

    def _fast_recovery_bear() -> bool:
        if not FAST_RECOVERY_ENABLED:
            return False
        _pierced = p_high > p_vwap * (1.0 + _TOUCH_PCT)
        _range = max(float(curr["high"]) - float(curr["low"]), 0.0001)
        _body  = abs(c_close - float(curr.get("open", c_close)))
        _strong_body = (_body / _range) > FAST_RECOVERY_MIN_BODY_PCT
        return _pierced and c_close < c_vwap and _strong_body

    # ── Trend-direction gates (2026-07-15 rework) ─────────────────────────────
    # VWAP slope: don't buy pullbacks to a descending VWAP (distribution) or
    # short bounces off an ascending one. EMA50 slope: level check alone isn't
    # a trend — the docstring promise "EMA50 trending up/down" now enforced.
    _TOUCH_PCT = 0.002   # prev bar must tap within 0.2% of VWAP — a real touch
    if len(today) >= 6:
        _vwap_5ago  = float(today["vwap"].iloc[-6])  if not pd.isna(today["vwap"].iloc[-6])  else c_vwap
        _ema50_5ago = float(today["ema50"].iloc[-6]) if not pd.isna(today["ema50"].iloc[-6]) else c_ema50
    else:
        _vwap_5ago, _ema50_5ago = c_vwap, c_ema50
    _vwap_rising   = c_vwap  > _vwap_5ago
    _vwap_falling  = c_vwap  < _vwap_5ago
    _ema50_rising  = c_ema50 > _ema50_5ago
    _ema50_falling = c_ema50 < _ema50_5ago

    # ── Bullish pullback ──────────────────────────────────────────────────────
    rvol_min_bull = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bull)

    _bull_touch = (
        p_low  <= p_vwap and                           # prev bar touched VWAP...
        p_low  >= p_vwap * (1.0 - _TOUCH_PCT)          # ...within 0.2% (tap, not pierce)
    )
    _bull_fast_recovery = _fast_recovery_bull()
    _bull_rejection_ok = (
        not CANDLESTICK_FILTER_ENABLED
        or is_hammer(prev, min_wick_ratio=CANDLESTICK_MIN_WICK_RATIO)
    )

    _bull_conditions = (
        c_close > c_ema50 and
        c_vwap  > c_ema50 and
        _ema50_rising and                              # EMA50 actually trending up
        _vwap_rising and                               # never buy a descending VWAP
        (_bull_touch or _bull_fast_recovery) and
        _bull_rejection_ok and                          # touch bar must be a hammer, if enabled
        c_close > c_vwap and
        c_rvol >= rvol_min_bull
    )
    _bull_blowthrough_ok = _bull_fast_recovery or _was_above_vwap(_lookback_bars)
    if _bull_conditions and not _bull_blowthrough_ok:
        logger.debug("[%s] VWAP_PB bullish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    _bull_pullback_n = (
        _count_prior_pullbacks(today, "bullish", _TOUCH_PCT, lookback=_PULLBACK_LOOKBACK)
        if _bull_conditions else 0
    )
    _bull_pullback_ok = MAX_PULLBACK_COUNT is None or _bull_pullback_n < MAX_PULLBACK_COUNT
    if _bull_conditions and not _bull_pullback_ok:
        logger.debug("[%s] VWAP_PB bullish: this is pullback #%d (max %d) — trend likely losing steam",
                     ticker, _bull_pullback_n + 1, MAX_PULLBACK_COUNT)

    if _bull_conditions and _bull_blowthrough_ok and _bull_pullback_ok:
        proximity  = max(0.0, 1.0 - abs(p_low - p_vwap) / max(p_vwap * _TOUCH_PCT, 0.01))
        confidence = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - rvol_min_bull, 1.0) * 0.07)
        logger.info("[%s] VWAP_PB bullish RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
                    ticker, c_rvol, rvol_min_bull, msa_ok_bull, confidence)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = "bullish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "vwap":           c_vwap,
                "ema50":          c_ema50,
                "prev_low":       p_low,
                "vwap_touch":     p_low <= p_vwap,
                "entry_bar_low":  float(curr["low"]),
                "msa_confirmed":  msa_ok_bull,
                "pullback_number": _bull_pullback_n + 1,
                "rvol_gate":        round(rvol_min_bull, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bull),
            },
        )

    # ── Bearish pullback ──────────────────────────────────────────────────────
    rvol_min_bear = _get_dynamic_rvol_threshold(
        bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bear)

    _bear_touch = (
        p_high >= p_vwap and                           # prev bar touched VWAP...
        p_high <= p_vwap * (1.0 + _TOUCH_PCT)          # ...within 0.2% (tap, not pierce)
    )
    _bear_fast_recovery = _fast_recovery_bear()
    _bear_rejection_ok = (
        not CANDLESTICK_FILTER_ENABLED
        or is_shooting_star(prev, min_wick_ratio=CANDLESTICK_MIN_WICK_RATIO)
    )

    _bear_conditions = (
        c_close < c_ema50 and
        c_vwap  < c_ema50 and
        _ema50_falling and                             # EMA50 actually trending down
        _vwap_falling and                              # never short an ascending VWAP
        (_bear_touch or _bear_fast_recovery) and
        _bear_rejection_ok and                          # touch bar must be a shooting star, if enabled
        c_close < c_vwap and
        c_rvol >= rvol_min_bear
    )
    _bear_blowthrough_ok = _bear_fast_recovery or _was_below_vwap(_lookback_bars)
    if _bear_conditions and not _bear_blowthrough_ok:
        logger.debug("[%s] VWAP_PB bearish: blowthrough detected — price crashed through VWAP, not a pullback",
                     ticker)

    _bear_pullback_n = (
        _count_prior_pullbacks(today, "bearish", _TOUCH_PCT, lookback=_PULLBACK_LOOKBACK)
        if _bear_conditions else 0
    )
    _bear_pullback_ok = MAX_PULLBACK_COUNT is None or _bear_pullback_n < MAX_PULLBACK_COUNT
    if _bear_conditions and not _bear_pullback_ok:
        logger.debug("[%s] VWAP_PB bearish: this is pullback #%d (max %d) — trend likely losing steam",
                     ticker, _bear_pullback_n + 1, MAX_PULLBACK_COUNT)

    if _bear_conditions and _bear_blowthrough_ok and _bear_pullback_ok:
        proximity  = max(0.0, 1.0 - abs(p_high - p_vwap) / max(p_vwap * _TOUCH_PCT, 0.01))
        confidence = min(0.82, 0.60 + proximity * 0.15 + min(c_rvol - rvol_min_bear, 1.0) * 0.07)
        logger.info("[%s] VWAP_PB bearish RVOL=%.2f (min=%.2f msa=%s) conf=%.2f",
                    ticker, c_rvol, rvol_min_bear, msa_ok_bear, confidence)
        return Signal(
            strategy_id = STRATEGY_ID,
            direction   = "bearish",
            confidence  = confidence,
            rvol        = c_rvol,
            trigger_bar = bar_time,
            meta        = {
                "vwap":            c_vwap,
                "ema50":           c_ema50,
                "prev_high":       p_high,
                "vwap_touch":      p_high >= p_vwap,
                "entry_bar_high":  float(curr["high"]),
                "msa_confirmed":   msa_ok_bear,
                "pullback_number": _bear_pullback_n + 1,
                "rvol_gate":        round(rvol_min_bear, 2),
                "rvol_gate_reason": _rvol_threshold_reason(
                    bar_min, c_close, None, c_vwap, STRATEGY_ID, msa_confirmed=msa_ok_bear),
            },
        )

    return None
