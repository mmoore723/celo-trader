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
  5. apply_mtf_confirmation       (confidence tax/boost — OFF by default, live-only)
  5b. apply_grade_filter          (filter — OFF by default, mirrors dashboard grade)
  6. apply_large_move_gate        (confidence cap)
  7. apply_directional_consensus  (filter or penalty)
  8. apply_confidence_floor       (filter)
  9. check_conflict_veto          (early return if True)
  10. check_volume_roc_veto       (early return if True)
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
from signal_journal import log_signal_outcome as _log_journal

logger = logging.getLogger("celo_trader.router_gates")


def _journal_dropped(before: list, after: list, ticker: str, reason_code: str, reason_detail: str = "") -> None:
    """
    Write one signal_journal 'blocked' row per signal a gate just removed.
    Shared by every hard-block gate below so the diff logic lives in one
    place — compares by id() since signal objects aren't hashable/comparable.
    """
    _after_ids = {id(s) for s in after}
    for _s in before:
        if id(_s) in _after_ids:
            continue
        try:
            _log_journal(ticker, _s.strategy_id, _s.direction, _s.confidence,
                         outcome="blocked", reason_code=reason_code, reason_detail=reason_detail)
        except Exception:
            pass   # journal writes are never allowed to affect gate behavior


# ── 1. Regime gate (OFF by default — see regime_manager.py) ──────────────────

def apply_regime_gate(signals: list, df: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not (_regime_mgr.REGIME_GATE_ENABLED and signals):
        return signals
    _regime = compute_regime(df)
    if _regime == "neutral":
        return signals
    _before_list = list(signals)
    signals = [s for s in signals if regime_allows(s.strategy_id, s.direction, _regime)]
    if len(signals) != len(_before_list) and not quiet:
        _journal_dropped(_before_list, signals, ticker, "regime_gate", f"regime={_regime}")
        try:
            _db_log("INFO", "bar_eval",
                    f"⚪ [{ticker}] Regime={_regime} filtered "
                    f"{len(_before_list) - len(signals)} counter-regime signal(s).")
        except Exception:
            pass
    return signals


# ── 2. Session bias penalty ───────────────────────────────────────────────────
# Compare current price to the session open price only. VWAP is intentionally
# excluded — individual strategies already gate on it. Penalty scales with
# RVOL so high-volume days allow more counter-session latitude.

def apply_session_bias_penalty(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
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
    if _penalized and not quiet:
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

def apply_confluence_bonus(signals: list, ticker: str, quiet: bool = False) -> list:
    if not signals:
        return signals
    _top_dir     = signals[0].direction
    _agree_count = sum(1 for _s in signals if _s.direction == _top_dir)
    if _agree_count >= 2:
        _conf_bonus  = min(0.05, (_agree_count - 1) * 0.03)
        _old_top     = signals[0].confidence
        signals[0].confidence = min(0.95, signals[0].confidence + _conf_bonus)
        if not quiet:
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


# ── 5. MTF confirmation (2026-07-23, professional-strategy-alignment audit) ──
# Gap 3: higher-timeframe (1Hour) agreement is a soft confidence tax/boost —
# NOT a hard block, and OFF by default. This is the one gate in this file
# that can't be backtested the normal way (see trading/mtf_live_gate.py's
# docstring) — it only does anything when the live call site passes a real
# `alpaca` client + per-user `mtf_cache` dict; every other caller (backtester,
# audit tools) leaves both None and this is a complete no-op, unchanged
# behavior. Applies uniformly to every strategy's signals, not just one —
# this is how "align the other strategies with it" was implemented: one
# shared gate in the pipeline instead of duplicating logic per strategy file.

_MTF_BOOST   = 0.05   # 1Hour agrees with the signal's direction
# 2026-07-31: was 0.05. At that size the penalty almost never mattered —
# most signals clear the 0.74 confidence floor with enough room that a
# 5-point ding doesn't change the outcome. Research (Elder's Triple Screen
# and general MTF-confirmation literature) treats higher-timeframe
# disagreement as a real, consequential signal, not a rounding error —
# aligned setups run meaningfully higher win rates than counter-trend ones.
# Raised to 0.12 so a disagreeing 1Hour trend can actually push a borderline
# signal below the floor. Still a SOFT adjustment, never a hard block, per
# CLAUDE.md rule 12 — a strong enough signal can still absorb this and trade.
_MTF_PENALTY = 0.12   # 1Hour disagrees with the signal's direction

# ── 5b. Minimum-grade filter (OFF by default) ─────────────────────────────────
# 2026-07-24: the dashboard's premarket report already grades every ticker
# A+/A/B/C/Watch (api/routes/market.py::_grade()) but that grade was DISPLAY
# ONLY — never read by live entry logic, so a "Watch"-grade ticker with no
# real setup could still fire a real trade if it happened to pass a
# strategy's own internal gates. This mirrors that same grading formula so a
# blocked entry matches what the dashboard shows, and blocks entries below a
# configurable minimum grade (default cutoff "C" — only "Watch" is blocked).
#
# KNOWN FIDELITY GAP: this uses strategy_router's own rvol (compute_rvol(),
# 10-day lookback) and atr, not market.py's separately-computed time-
# normalized live rvol — the two methods can disagree slightly since they're
# genuinely different calculations. Exact parity would require unifying both
# call sites onto one shared rvol function; out of scope for this gate.
from scanner import _ETF_SET as _GRADE_ETF_SET

_GRADE_ORDER = {"Watch": 0, "C": 1, "B": 2, "A": 3, "A+": 4}


def _grade_from_metrics(gap_pct: float, rvol: float, atr: float, is_etf: bool) -> str:
    """Mirrors api/routes/market.py::_grade() — keep both in sync if either changes."""
    ag   = abs(gap_pct)
    gmin = 0.5 if is_etf else 1.0
    if ag >= 2.0 and rvol >= 2.5 and atr >= 1.5:
        return "A+"
    if ag >= gmin and rvol >= 2.0 and atr >= 1.0:
        return "A"
    if ag >= gmin * 0.5 and rvol >= 1.5:
        return "B"
    if ag >= gmin * 0.25:
        return "C"
    return "Watch"


def apply_grade_filter(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
    if not signals or len(today) == 0:
        return signals
    _s = _get_settings()
    if not bool(_s.get("min_grade_filter_enabled", False)):
        return signals
    _min_grade = str(_s.get("min_entry_grade", "C"))
    if _min_grade not in _GRADE_ORDER:
        _min_grade = "C"

    _last = today.iloc[-1]
    _gap  = float(_last.get("session_gap_pct", 0.0) or 0.0)
    _rvol = float(_last.get("rvol", 0.0) or 0.0)
    _atr  = float(_last.get("atr", 0.0) or 0.0)
    _grade = _grade_from_metrics(_gap, _rvol, _atr, ticker in _GRADE_ETF_SET)

    if _GRADE_ORDER[_grade] >= _GRADE_ORDER[_min_grade]:
        return signals

    if not quiet:
        _journal_dropped(signals, [], ticker, "grade_filter",
                          f"{_grade} grade below minimum {_min_grade} "
                          f"(gap={_gap:+.2f}%, rvol={_rvol:.1f}x, atr=${_atr:.2f})")
        _db_log("INFO", "bar_eval",
                f"⚪ [{ticker}] Grade filter: {_grade} setup (gap={_gap:+.2f}%, "
                f"rvol={_rvol:.1f}x, atr=${_atr:.2f}) below minimum {_min_grade} "
                f"— {len(signals)} entry signal(s) blocked.")
        logger.info("router: grade filter blocked %s (%s < %s)", ticker, _grade, _min_grade)
    return []

def apply_mtf_confirmation(signals: list, ticker: str, alpaca=None, mtf_cache: dict | None = None,
                            quiet: bool = False) -> list:
    if not signals or alpaca is None or mtf_cache is None:
        return signals   # no-op unless the live call site opted in
    from config import get_settings as _gs
    if not bool(_gs().get("mtf_confirmation_enabled", False)):
        return signals

    from trading.mtf_live_gate import get_live_1h_bias
    for sig in signals:
        bias = get_live_1h_bias(alpaca, ticker, sig.direction, mtf_cache)
        if bias == "with":
            sig.confidence = min(0.95, sig.confidence + _MTF_BOOST)
        elif bias == "against":
            sig.confidence = max(0.0, sig.confidence - _MTF_PENALTY)
        # "neutral" (no data / insufficient history) — leave confidence as-is
        if bias != "neutral" and not quiet:
            logger.debug("[%s] %s: 1Hour bias %s (%s)", ticker, sig.strategy_id, bias, sig.direction)
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 6. Large-session-move gate (gap / momentum-day filter) ───────────────────
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


# ── 7. Directional consensus filter ───────────────────────────────────────────
# Three independent indicators (price vs VWAP, VWAP slope, market structure)
# must ALL agree before a direction is considered "established" enough to
# hard-block the opposite side. 2/3 agreement gets a soft penalty instead.

def apply_directional_consensus(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> list:
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

    _dc_before_list = list(signals)
    _dc_before = len(signals)
    if _bull_score == 3:
        signals = [s for s in signals if s.direction == "bullish"]
        if _dc_before > len(signals) and not quiet:
            _journal_dropped(_dc_before_list, signals, ticker, "directional_consensus",
                              f"3/3 bullish (slope+{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}x)")
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
        if _dc_before > len(signals) and not quiet:
            _journal_dropped(_dc_before_list, signals, ticker, "directional_consensus",
                              f"3/3 bearish (slope{_dc_slope_pct*100:.2f}% {_dc_trend} RVOL {_dc_rvol:.1f}x)")
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


# ── 8. Confidence floor ───────────────────────────────────────────────────────

def apply_confidence_floor(signals: list, ticker: str, min_confidence: float, quiet: bool = False) -> list:
    # quiet=True added 2026-07-24 alongside the signal_journal write below —
    # without it, backtester.py's 1-min-resolution replay of route_signals()
    # (see backtester.py) would flood signal_journal with thousands of fake
    # historical rows every backtest run. Default False preserves the exact
    # prior behavior for the one live call site in strategy_router.py.
    _before_list = list(signals)
    signals = [s for s in signals if s.confidence >= min_confidence]
    if len(signals) < len(_before_list) and not quiet:
        _dropped = len(_before_list) - len(signals)
        _journal_dropped(_before_list, signals, ticker, "confidence_floor",
                          f"below {min_confidence:.0%} floor")
        logger.info(
            "router: dropped %d low-confidence signal(s) for %s (floor=%.0f%%)",
            _dropped, ticker, min_confidence * 100,
        )
    return signals


# ── 9. Conflict veto (early return if True) ───────────────────────────────────
# If the top two signals disagree on direction and their confidence gap is
# within veto_band, the market is sending mixed signals — skip both.

def check_conflict_veto(signals: list, today: pd.DataFrame, ticker: str, veto_band: float, quiet: bool = False) -> bool:
    if len(signals) < 2:
        return False
    _top, _second = signals[0], signals[1]
    if not (_top.direction != _second.direction and
            (_top.confidence - _second.confidence) <= veto_band):
        return False

    if quiet:
        return True

    _detail = f"{_top.strategy_id} {_top.direction} vs {_second.strategy_id} {_second.direction} within {veto_band:.0%}"
    _journal_dropped([_top, _second], [], ticker, "conflict_veto", _detail)

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


# ── 10. Volume ROC gate (early return if True) ────────────────────────────────
# Prevent entries when buying pressure is already fading. Compares avg volume
# of the last 3 bars vs the prior 3 bars.

def check_volume_roc_veto(signals: list, today: pd.DataFrame, ticker: str, quiet: bool = False) -> bool:
    if not (signals and len(today) >= 6):
        return False

    _recent_vol = today["volume"].iloc[-3:].mean()
    _prior_vol  = today["volume"].iloc[-6:-3].mean()
    _vol_roc    = _recent_vol / _prior_vol if _prior_vol > 0 else 1.0

    _roc_threshold = float(_get_settings().get("vol_roc_threshold", 0.50))
    if _vol_roc >= _roc_threshold:
        return False

    if quiet:
        return True

    _journal_dropped(signals, [], ticker, "volume_roc_veto",
                      f"ROC {_vol_roc:.2f} < {_roc_threshold:.2f}")

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
