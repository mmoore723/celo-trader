"""
router_gates.py — Sequential signal-quality gates applied by strategy_router.

Extracted from strategy_router.py (2026-07-16) to keep the router itself
under ~200 lines. Each function takes the current signals list (plus the
indicator frame / ticker it needs) and returns the filtered/adjusted list.
Two gates (conflict veto, volume ROC) are "check_*" functions instead —
they return a bool because a True result means route_signals() must return
[] IMMEDIATELY, skipping every gate after it and the final audit-log call.
That early-return behavior is preserved exactly as it was inline before
this extraction — do not change these two to plain filters without also
updating strategy_router.route_signals()'s early-return checks.

Pipeline order (must match strategy_router.route_signals()):
  1. apply_regime_gate            (filter — OFF by default, see regime_manager.py)
  2. apply_session_bias_penalty   (confidence tax)
  3. apply_vwap_weight            (confidence tax)
  4. apply_confluence_bonus       (confidence boost)
  5. apply_large_move_gate        (confidence cap)
  6. apply_directional_consensus  (filter or penalty)
  7. apply_confidence_floor       (filter)
  8. check_conflict_veto          (early return if True)
  9. check_volume_roc_veto        (early return if True)
"""

from __future__ import annotations

import logging

import pandas as pd

from database import log_event as _db_log
from config import get_settings as _get_settings
from trading.annotations import emit_annotation as _emit_ann
from strategies.base import MarketStructureAnalyzer
import regime_manager as _regime_mgr
from regime_manager import compute_regime, regime_allows

logger = logging.getLogger("celo_trader.router_gates")


# ── 1. Regime gate (OFF by default — see regime_manager.py) ──────────────────

def apply_regime_gate(signals: list, df: pd.DataFrame, ticker: str) -> list:
    if not (_regime_mgr.REGIME_GATE_ENABLED and signals):
        return signals
    _regime = compute_regime(df)
    if _regime == "neutral":
        return signals
    _before = len(signals)
    signals = [s for s in signals if regime_allows(s.strategy_id, s.direction, _regime)]
    if len(signals) != _before:
        try:
            _db_log("INFO", "bar_eval",
                    f"⚪ [{ticker}] Regime={_regime} filtered "
                    f"{_before - len(signals)} counter-regime signal(s).")
        except Exception:
            pass
    return signals


# ── 2. Session bias penalty ───────────────────────────────────────────────────
# Compare current price to the session open price only. VWAP is intentionally
# excluded — individual strategies already gate on it. Penalty scales with
# RVOL so high-volume days allow more counter-session latitude.

def apply_session_bias_penalty(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 2):
        return signals

    _first_bar    = today.iloc[0]
    _last_bar     = today.iloc[-1]
    _session_open = float(_first_bar.get("open", _first_bar["close"]))
    _curr_close   = float(_last_bar["close"])

    _session_bearish = _curr_close < _session_open
    _session_bullish = _curr_close > _session_open
    if not (_session_bearish or _session_bullish):
        return signals

    _bias_label = "bearish" if _session_bearish else "bullish"
    _penalized  = 0

    _last_rvol = float(_last_bar.get("rvol", 1.0) or 1.0)
    if _last_rvol > 1.5:
        _dynamic_penalty = 0.02   # high volume — V-reversals are real
    elif _last_rvol < 1.0:
        _dynamic_penalty = 0.10   # low volume — counter-trend = chop
    else:
        _dynamic_penalty = 0.05   # normal days

    for _sig in signals:
        _counter = (
            (_session_bearish and _sig.direction == "bullish") or
            (_session_bullish and _sig.direction == "bearish")
        )
        if _counter:
            _old_conf       = _sig.confidence
            _sig.confidence = max(0.0, _sig.confidence - _dynamic_penalty)
            _penalized      += 1
            logger.debug(
                "router: session_bias=%s penalized %s %s conf %.2f→%.2f (rvol=%.2f penalty=%.0f%%)",
                _bias_label, _sig.strategy_id, _sig.direction,
                _old_conf, _sig.confidence, _last_rvol, _dynamic_penalty * 100,
            )
    if _penalized:
        _db_log(
            "INFO", "scan",
            f"{ticker} — Session bias={_bias_label}: "
            f"{_penalized} counter-session signal(s) penalized -{_dynamic_penalty:.0%} "
            f"(RVOL={_last_rvol:.1f}× | close={_curr_close:.2f} vs session_open={_session_open:.2f})",
        )
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 3. Intraday VWAP trend — weighted 20% factor ─────────────────────────────
# VWAP slope is ONE input, not a binary gate. It contributes 20% weight to
# signal confidence; the strategy's own technical edge provides 80%.

def apply_vwap_weight(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 12):
        return signals

    _vwap_now   = float(today.iloc[-1].get("vwap", 0) or 0)
    _vwap_10    = float(today.iloc[-10].get("vwap", _vwap_now) or _vwap_now)
    _vwap_slope = (_vwap_now - _vwap_10) / max(_vwap_10, 1.0)

    _VWAP_SLOPE_THRESH = 0.0005   # 0.05% over 10 bars = clear institutional flow
    _VWAP_WEIGHT       = 0.20     # VWAP trend accounts for 20% of signal weight

    _slope_adjusted = 0
    for _sig in signals:
        _against_flow = (
            (_vwap_slope < -_VWAP_SLOPE_THRESH and _sig.direction == "bullish") or
            (_vwap_slope >  _VWAP_SLOPE_THRESH and _sig.direction == "bearish")
        )
        if _against_flow:
            _old_conf = _sig.confidence
            _sig.confidence = round(max(0.0, _sig.confidence * (1.0 - _VWAP_WEIGHT)), 4)
            _slope_adjusted += 1
            logger.debug(
                "router: vwap_weighted ×0.80: %s %s conf %.3f→%.3f (slope=%.3f%% flow=%s)",
                _sig.strategy_id, _sig.direction, _old_conf, _sig.confidence,
                _vwap_slope * 100, "bearish" if _vwap_slope < 0 else "bullish",
            )

    if _slope_adjusted:
        _flow_dir = "bearish" if _vwap_slope < 0 else "bullish"
        logger.debug(
            "router: vwap_weighted 20%% factor applied to %d counter-flow signal(s) "
            "— intraday flow=%s (slope=%.3f%%)",
            _slope_adjusted, _flow_dir, _vwap_slope * 100,
        )
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 4. Confluence bonus ───────────────────────────────────────────────────────
# When 2+ independent strategies agree on direction, this is the highest-
# probability setup. Reward it with a confidence bonus.

def apply_confluence_bonus(signals: list, ticker: str) -> list:
    if not signals:
        return signals
    _top_dir     = signals[0].direction
    _agree_count = sum(1 for _s in signals if _s.direction == _top_dir)
    if _agree_count >= 2:
        _conf_bonus  = min(0.05, (_agree_count - 1) * 0.03)
        _old_top     = signals[0].confidence
        signals[0].confidence = min(0.95, signals[0].confidence + _conf_bonus)
        logger.info(
            "router: confluence +%.0f%% for %s %s (%d strategies agree: %.0f%%→%.0f%%)",
            _conf_bonus * 100, ticker, _top_dir, _agree_count,
            _old_top * 100, signals[0].confidence * 100,
        )
        _db_log(
            "INFO", "scan",
            f"{ticker} — Confluence: {_agree_count} strategies agree {_top_dir} "
            f"→ confidence boosted +{_conf_bonus:.0%} to {signals[0].confidence:.0%}",
        )
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 5. Large-session-move gate (gap / momentum-day filter) ───────────────────
# If the session has already moved ±1.5%+ from the opening bar, it is a gap
# or momentum day. Counter-trend entries before 13:00 ET are high-risk.

def apply_large_move_gate(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 2):
        return signals

    _so     = float(today.iloc[0].get("open", today.iloc[0]["close"]))
    _sc     = float(today.iloc[-1]["close"])
    _sm_pct = (_sc - _so) / max(_so, 1.0)
    _btime  = today.iloc[-1]["time"]
    _bmin   = (_btime.hour * 60 + _btime.minute) if hasattr(_btime, "hour") else 600

    _LARGE_MOVE = 0.015   # 1.5% from open = gap/momentum day
    if abs(_sm_pct) > _LARGE_MOVE and _bmin < 13 * 60:
        _trend_dir = "bullish" if _sm_pct > 0 else "bearish"
        _capped    = 0
        for _sig in signals:
            if _sig.direction != _trend_dir:
                _sig.confidence = min(_sig.confidence, 0.70)   # below 0.74 floor
                _capped += 1
        if _capped:
            logger.info(
                "router: large_session_move=%.1f%% before 13:00 — "
                "%d counter-trend signal(s) capped (trend=%s)",
                _sm_pct * 100, _capped, _trend_dir,
            )
            signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 6. Directional consensus filter ───────────────────────────────────────────
# Three independent indicators (price vs VWAP, VWAP slope, market structure)
# must ALL agree before a direction is considered "established" enough to
# hard-block the opposite side. 2/3 agreement gets a soft penalty instead.

def apply_directional_consensus(signals: list, today: pd.DataFrame, ticker: str) -> list:
    if not (signals and len(today) >= 20):
        return signals

    _dc_last   = today.iloc[-1]
    _dc_rvol   = float(_dc_last.get("rvol", 1.0) or 1.0)
    _dc_close  = float(_dc_last["close"])
    _dc_vwap   = float(_dc_last.get("vwap", _dc_close) or _dc_close)

    _dc_price_bull = _dc_close > _dc_vwap
    _dc_price_bear = _dc_close < _dc_vwap

    _dc_vwap_20    = float(today.iloc[-20].get("vwap", _dc_vwap) or _dc_vwap)
    _dc_slope_pct  = (_dc_vwap - _dc_vwap_20) / max(_dc_vwap_20, 1.0)
    _dc_slope_bull = _dc_slope_pct > 0.0005    # +0.05% over 100 min
    _dc_slope_bear = _dc_slope_pct < -0.0005

    _dc_msa    = MarketStructureAnalyzer(today)
    _dc_trend  = _dc_msa.classify_trend()
    _dc_struct_bull = _dc_trend == "uptrend"
    _dc_struct_bear = _dc_trend == "downtrend"

    _bull_score = sum([_dc_price_bull, _dc_slope_bull, _dc_struct_bull])
    _bear_score = sum([_dc_price_bear, _dc_slope_bear, _dc_struct_bear])

    _dc_before = len(signals)
    if _bull_score == 3:
        signals = [s for s in signals if s.direction == "bullish"]
        if _dc_before > len(signals):
            logger.info(
                "router: dir_consensus=BULLISH 3/3 (slope+%.3f%% %s RVOL=%.1f×) — %d PUT(s) blocked",
                _dc_slope_pct * 100, _dc_trend, _dc_rvol, _dc_before - len(signals),
            )
            _db_log("INFO", "scan",
                f"{ticker} — Directional consensus BULLISH 3/3 "
                f"(price>VWAP slope+{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}×) "
                f"— PUT entries blocked.")
    elif _bear_score == 3:
        signals = [s for s in signals if s.direction == "bearish"]
        if _dc_before > len(signals):
            logger.info(
                "router: dir_consensus=BEARISH 3/3 (slope%.3f%% %s RVOL=%.1f×) — %d CALL(s) blocked",
                _dc_slope_pct * 100, _dc_trend, _dc_rvol, _dc_before - len(signals),
            )
            _db_log("INFO", "scan",
                f"{ticker} — Directional consensus BEARISH 3/3 "
                f"(price<VWAP slope{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}×) "
                f"— CALL entries blocked.")
    else:
        # Soft penalty only: 2/3 lean → reduce counter-direction by 20%
        if _bull_score == 2:
            for _s in signals:
                if _s.direction == "bearish":
                    _s.confidence = round(max(0.0, _s.confidence * 0.80), 4)
        elif _bear_score == 2:
            for _s in signals:
                if _s.direction == "bullish":
                    _s.confidence = round(max(0.0, _s.confidence * 0.80), 4)

    if len(signals) != _dc_before:
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 7. Confidence floor ───────────────────────────────────────────────────────

def apply_confidence_floor(signals: list, ticker: str, min_confidence: float) -> list:
    _before_floor = len(signals)
    signals = [s for s in signals if s.confidence >= min_confidence]
    if len(signals) < _before_floor:
        _dropped = _before_floor - len(signals)
        logger.info(
            "router: dropped %d low-confidence signal(s) for %s (floor=%.0f%%)",
            _dropped, ticker, min_confidence * 100,
        )
    return signals


# ── 8. Conflict veto (early return if True) ───────────────────────────────────
# If the top two signals disagree on direction and their confidence gap is
# within veto_band, the market is sending mixed signals — skip both.

def check_conflict_veto(signals: list, today: pd.DataFrame, ticker: str, veto_band: float) -> bool:
    if len(signals) < 2:
        return False
    _top, _second = signals[0], signals[1]
    if not (_top.direction != _second.direction and
            (_top.confidence - _second.confidence) <= veto_band):
        return False

    _db_log(
        "INFO", "scan",
        f"{ticker} — Conflict veto: {_top.strategy_id} {_top.direction} "
        f"({_top.confidence:.0%}) vs {_second.strategy_id} {_second.direction} "
        f"({_second.confidence:.0%}) within {veto_band:.0%} band — "
        f"market is ambiguous, skipping both.",
    )
    logger.info(
        "router: conflict veto fired for %s (%s vs %s)",
        ticker, _top.strategy_id, _second.strategy_id,
    )
    try:
        _cv_ts = str(today.iloc[-1]["time"])
        _cv_px = float(today.iloc[-1]["close"])
        _emit_ann(ticker, "marker", "veto",
                  label=f"✗ Conflict {_top.strategy_id}↑↓{_second.strategy_id}",
                  ts=_cv_ts, price=_cv_px, color="#64748b")
    except Exception:
        pass
    return True


# ── 9. Volume ROC gate (early return if True) ─────────────────────────────────
# Prevent entries when buying pressure is already fading. Compares avg volume
# of the last 3 bars vs the prior 3 bars.

def check_volume_roc_veto(signals: list, today: pd.DataFrame, ticker: str) -> bool:
    if not (signals and len(today) >= 6):
        return False

    _recent_vol = today["volume"].iloc[-3:].mean()
    _prior_vol  = today["volume"].iloc[-6:-3].mean()
    _vol_roc    = _recent_vol / _prior_vol if _prior_vol > 0 else 1.0

    _roc_threshold = float(_get_settings().get("vol_roc_threshold", 0.50))
    if _vol_roc >= _roc_threshold:
        return False

    _db_log(
        "INFO", "scan",
        f"{ticker} — Volume ROC veto: recent vol {_recent_vol:.0f} "
        f"vs prior {_prior_vol:.0f} (ROC={_vol_roc:.2f} < {_roc_threshold:.2f}) "
        f"— fading momentum, staying in cash.",
    )
    logger.info(
        "router: vol_roc_veto %s — vol declining %.0f%% (%.0f → %.0f)",
        ticker, (1 - _vol_roc) * 100, _prior_vol, _recent_vol,
    )
    try:
        _veto_ts = str(today.iloc[-1]["time"])
        _veto_px = float(today.iloc[-1]["close"])
        _emit_ann(ticker, "marker", "veto",
                  label=f"✗ Vol ROC {_vol_roc:.2f}",
                  ts=_veto_ts, price=_veto_px, color="#64748b")
    except Exception:
        pass
    return True
