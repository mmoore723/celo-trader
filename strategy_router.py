"""
strategy_router.py — Dynamic Multi-Strategy Signal Router

Thin orchestrator: builds the indicator frame once per tick, calls each
strategy module's evaluate() function, and returns signals ranked by
confidence.  All evaluation logic lives in strategies/.

Strategy IDs (seven active):
  INST_ORB    — strategies/inst_orb.py   (09:45–10:30)
  VWAP_PB     — strategies/vwap_pb.py   (09:45–EOD)
  FVG         — strategies/fvg.py        (09:45–EOD)  ← absorbs BOS_MSS sweep logic
  MID_BRK     — strategies/mid_brk.py   (10:30–13:00)
  AFT_REV     — strategies/aft_rev.py   (13:00–15:30)
  TREND_CONT  — strategies/trend_cont.py (09:45–14:30)
  CHAN_BREAK  — strategies/chan_break.py (09:45–14:00)

  BOS_MSS (strategies/bos_mss.py) — DISABLED; its sweep detection was merged
  into FVG as a confidence modifier (running both double-voted the same move).

All signals pass through RiskManager gates in risk.py before entry:
  • 1% risk rule  • 1.6 R:R minimum  • 20% hard stop  • time-box exit
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from signals import (
    compute_vwap_bands,
    compute_rvol,
)
from risk import check_kill_lock
from database import log_event as _db_log
from config import get_settings as _get_settings
from trading.annotations import emit_annotation as _emit_ann

# ── Re-export Signal + MSA so callers that import from strategy_router still work ─
from strategies.base import Signal, MarketStructureAnalyzer  # noqa: F401

# ── Strategy evaluator modules ────────────────────────────────────────────────
from strategies import inst_orb, bos_mss, vwap_pb, fvg, ifvg, mid_brk, aft_rev, trend_cont, chan_break

logger = logging.getLogger("celo_trader.strategy_router")

# ── Router quality gates ───────────────────────────────────────────────────────
# Confidence floor: strategies score 0.75 at baseline with zero bonuses.
# Anything below is a marginal signal with no meaningful edge — drop it.
_MIN_CONFIDENCE = 0.74   # confidence floor — below this is noise, not edge

# Conflict veto window: if the top two signals disagree on direction AND their
# confidence scores are within this band, the router is ambiguous — return nothing.
_CONFLICT_VETO_BAND = 0.05

# Session bias penalty: applied when a signal goes against the session's own
# price action. This is a confidence tax, not a direction block.
_SESSION_BIAS_PENALTY = 0.05  # fallback default (overridden dynamically below)


# ── Audit state — tracks last-logged structure so we don't spam the DB ────────
_last_audit_state: dict = {}


# ── Chart annotation emitter ──────────────────────────────────────────────────

def _emit_signal_annotation(ticker: str, sig: "Signal", today: "pd.DataFrame") -> None:
    """
    Translate a strategy Signal into one or more chart overlays stored in
    LIVE_STATE["chart_annotations"][ticker].  Called immediately after a
    strategy fires so the drawing appears on the frontend chart in real time.

    Per-strategy rules:
      FVG / IFVG  → zone band (gap_low … gap_high)
      BOS_MSS     → hline at bos_level
      TREND_CONT  → hline at the swing re-entry level (lh_price or hl_price)
      INST_ORB    → hline at prior swing high/low that was broken
      AFT_REV     → hline at prior swing high/low
      VWAP_PB / MID_BRK → marker only (VWAP line already on chart)
    All strategies also emit a candle marker showing where the signal fired.
    """
    meta   = sig.meta or {}
    ts_str = (sig.trigger_bar.isoformat()
              if hasattr(sig.trigger_bar, "isoformat") else str(sig.trigger_bar))
    arrow  = "↑" if sig.direction == "bullish" else "↓"

    _last_close = float(today.iloc[-1]["close"]) if not today.empty else None

    # ── Zone overlays (FVG, IFVG) ─────────────────────────────────────────────
    if sig.strategy_id in ("FVG", "IFVG"):
        gl = meta.get("gap_low")
        gh = meta.get("gap_high")
        if gl is not None and gh is not None:
            _emit_ann(
                ticker, "zone", sig.strategy_id,
                label=f"{sig.strategy_id} {arrow}  {sig.confidence:.0%}",
                ts=ts_str, direction=sig.direction,
                price_low=gl, price_high=gh,
            )

    # ── Horizontal levels ─────────────────────────────────────────────────────
    elif sig.strategy_id == "BOS_MSS":
        lvl = meta.get("bos_level")
        if lvl:
            _emit_ann(ticker, "hline", "BOS_MSS",
                      label=f"BOS {arrow}  {sig.confidence:.0%}",
                      ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "TREND_CONT":
        lvl = meta.get("lh_price") or meta.get("hl_price")
        if lvl:
            _emit_ann(ticker, "hline", "TREND_CONT",
                      label=f"TC {arrow}  {sig.confidence:.0%}",
                      ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "INST_ORB":
        lvl = meta.get("prev_swing_high") or meta.get("prev_swing_low")
        if lvl:
            _emit_ann(ticker, "hline", "INST_ORB",
                      label=f"ORB {arrow}  {sig.confidence:.0%}",
                      ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "AFT_REV":
        lvl = meta.get("prev_swing_high") or meta.get("prev_swing_low")
        if lvl:
            _emit_ann(ticker, "hline", "AFT_REV",
                      label=f"AFT {arrow}  {sig.confidence:.0%}",
                      ts=ts_str, price=lvl, direction=sig.direction)

    # ── Candle marker for ALL strategies (shows where signal fired) ───────────
    if _last_close:
        sig_color = "#22c55e" if sig.direction == "bullish" else "#ef4444"
        _emit_ann(
            ticker, "marker", sig.strategy_id,
            label=f"{sig.strategy_id} {arrow}  {sig.confidence:.0%}",
            ts=ts_str, price=_last_close,
            direction=sig.direction, color=sig_color,
        )


# ── Indicator frame builder ───────────────────────────────────────────────────

def _build_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators shared by the strategy modules in a single pass.
    Returns an augmented DataFrame containing only today's bars.

    Columns added:
      vwap, vwap_upper1, vwap_lower1, vwap_upper2, vwap_lower2
      rvol       — 10-day true RVOL (falls back to 20-bar rolling proxy)
      ema50      — long-term trend filter
      atr        — 14-bar ATR for gap sizing + MFE gates
      vol_sma20  — 100-bar volume rolling mean (intraday reference)
    """
    if df.empty:
        return df

    latest_date = df["time"].dt.date.max()
    today       = df[df["time"].dt.date == latest_date].copy().reset_index(drop=True)

    # VWAP + standard deviation bands
    _vwap_frame      = compute_vwap_bands(today, num_stds=(1, 2))
    today["vwap"]        = _vwap_frame["vwap"].ffill()
    today["vwap_upper1"] = _vwap_frame["vwap_upper1"].ffill()
    today["vwap_lower1"] = _vwap_frame["vwap_lower1"].ffill()
    today["vwap_upper2"] = _vwap_frame["vwap_upper2"].ffill()
    today["vwap_lower2"] = _vwap_frame["vwap_lower2"].ffill()

    # RVOL — 10-day lookback if df has history, else 20-bar rolling proxy
    rvol_series      = compute_rvol(df, lookback_days=10)
    today["rvol"]    = rvol_series.reindex(today.index).fillna(1.0)

    # EMA50 — replaces EMA9/EMA21 (removed in earlier refactor)
    today["ema50"]   = today["close"].ewm(span=50, adjust=False).mean()

    # ATR14
    hl  = today["high"]  - today["low"]
    hcp = (today["high"]  - today["close"].shift(1)).abs()
    lcp = (today["low"]   - today["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    today["atr"]     = tr.ewm(span=14, adjust=False).mean()

    # 100-bar volume SMA (equivalent to old 20-bar SMA on 5-min bars)
    today["vol_sma20"] = today["volume"].rolling(100, min_periods=20).mean()

    return today


# ── ADX regime gate (2026-07-15 audit) ───────────────────────────────────────
# Breakout/continuation strategies need a TRENDING regime to work. ADX(14) on
# 5-min bars below 25 = mean-reverting chop — raw breakouts get stopped out
_ADX_PERIOD           = 14
_ADX_MIN              = 25.0
_ADX_GATED_STRATEGIES = {"INST_ORB", "MID_BRK", "TREND_CONT", "CHAN_BREAK"}


def compute_adx_series(df: pd.DataFrame, period: int = _ADX_PERIOD) -> "pd.Series | None":
    """
    Wilder ADX(14) computed on 5-min resampled bars.
    Accepts mixed-timeframe input (live passes 5-min history + today's 1-min).
    Returns a Series indexed by 5-min bucket timestamps, or None if not enough data.
    """
    try:
        d = df[["time", "high", "low", "close"]].dropna().copy()
        d = (d.set_index("time")
              .resample("5min")
              .agg({"high": "max", "low": "min", "close": "last"})
              .dropna())
        if len(d) < period * 2:
            return None   # not enough bars for a meaningful ADX

        up, dn   = d["high"].diff(), -d["low"].diff()
        plus_dm  = up.where((up > dn) & (up > 0), 0.0)   # +DM
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)   # -DM
        tr = pd.concat([d["high"] - d["low"],
                        (d["high"] - d["close"].shift()).abs(),
                        (d["low"]  - d["close"].shift()).abs()], axis=1).max(axis=1)

        alpha = 1.0 / period   # Wilder smoothing = EMA with alpha 1/N
        atr   = tr.ewm(alpha=alpha, adjust=False).mean()
        pdi   = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
        mdi   = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
        dx    = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, float("nan"))
        return dx.ewm(alpha=alpha, adjust=False).mean()
    except Exception as exc:
        logger.debug("compute_adx_series failed: %s", exc)
        return None


def compute_adx(df: pd.DataFrame, period: int = _ADX_PERIOD) -> "float | None":
    """Latest ADX value, or None if unavailable (fail-open: no gate applied)."""
    s = compute_adx_series(df, period)
    if s is None or s.empty:
        return None
    v = s.iloc[-1]
    return float(v) if pd.notna(v) else None


# ── Public router ─────────────────────────────────────────────────────────────

def route_signals(
    df: pd.DataFrame,
    ticker: str,
    enabled_strategies: "set[str] | None" = None,
) -> list[Signal]:
    """
    Evaluate all strategy modules against the current bar data.

    Args:
        df                  : Multi-day 5-min OHLCV DataFrame
        ticker              : Symbol string (log context + cooldown keying)
        enabled_strategies  : Optional set of strategy IDs to run.
                              If None, all eight run.

    Returns:
        list[Signal] sorted by confidence descending (may be empty).
    """
    if df.empty or len(df) < 2:
        return []

    # Kill-lock guard — skip all evaluators if daily loss cap hit
    _killed, _kill_reason = check_kill_lock()
    if _killed:
        logger.warning(
            "route_signals blocked by kill lock",
            extra={"event": "kill_lock_blocked", "reason": _kill_reason, "ticker": ticker},
        )
        return []

    today = _build_indicator_frame(df)
    if today.empty:
        return []

    signals: list[Signal] = []

    # Evaluator table — (strategy_id, module.evaluate)
    # Each module's evaluate() self-gates on its own session window.
    _all_evaluators = [
        ("INST_ORB",   inst_orb.evaluate),
        ("VWAP_PB",    vwap_pb.evaluate),
        ("FVG",        fvg.evaluate),
        ("IFVG",       ifvg.evaluate),    # Inverted FVG — zone-flip reversal
        ("MID_BRK",    mid_brk.evaluate),
        ("AFT_REV",    aft_rev.evaluate),
        ("TREND_CONT", trend_cont.evaluate),
        # ("CHAN_BREAK", chan_break.evaluate),  # disabled — 0% WR in backtests, needs fix
    ]
    evaluators = (
        [(sid, fn) for sid, fn in _all_evaluators if sid in enabled_strategies]
        if enabled_strategies is not None
        else _all_evaluators
    )

    # ── ADX regime gate — skip breakout strategies in chop (ADX < 25) ────────
    # Fail-open: if ADX can't be computed (thin data), no strategies are gated.
    _adx_now = compute_adx(df)
    if _adx_now is not None and _adx_now < _ADX_MIN:
        _gated = [sid for sid, _ in evaluators if sid in _ADX_GATED_STRATEGIES]
        if _gated:
            evaluators = [(sid, fn) for sid, fn in evaluators
                          if sid not in _ADX_GATED_STRATEGIES]
            try:
                _db_log("INFO", "bar_eval",
                        f"⚪ [{ticker}] ADX {_adx_now:.0f} < {_ADX_MIN:.0f} — chop regime. "
                        f"Breakout strategies gated: {', '.join(_gated)}. "
                        f"Mean-reversion strategies still active.")
            except Exception:
                pass
    if not evaluators:
        return []

    for strategy_id, fn in evaluators:
        try:
            # Pass ticker= so cooldown tracking and log context work correctly.
            sig = fn(today, ticker=ticker)
            if sig is not None:
                signals.append(sig)
                # Emit chart annotation so the frontend can draw this signal
                try:
                    _emit_signal_annotation(ticker, sig, today)
                except Exception:
                    pass   # annotation failure must never crash the router
                logger.info(
                    "strategy_signal",
                    extra={
                        "event":       "strategy_signal",
                        "strategy_id": strategy_id,
                        "ticker":      ticker,
                        "direction":   sig.direction,
                        "confidence":  round(sig.confidence, 3),
                        "rvol":        round(sig.rvol, 2),
                    },
                )
        except Exception as exc:
            logger.warning("Strategy %s raised: %s", strategy_id, exc, exc_info=True)

    signals.sort(key=lambda s: s.confidence, reverse=True)

    # ── Session bias penalty ──────────────────────────────────────────────────
    # Compare current price to the session open price only.
    # VWAP is intentionally excluded — individual strategies already gate on it.
    if signals and len(today) >= 2:
        _first_bar    = today.iloc[0]
        _last_bar     = today.iloc[-1]
        _session_open = float(_first_bar.get("open", _first_bar["close"]))
        _curr_close   = float(_last_bar["close"])

        _session_bearish = _curr_close < _session_open
        _session_bullish = _curr_close > _session_open

        if _session_bearish or _session_bullish:
            _bias_label  = "bearish" if _session_bearish else "bullish"
            _penalized   = 0

            # Dynamic penalty: scale with current RVOL so high-volume days
            # allow more counter-session latitude, and quiet days penalize hard.
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
                    _penalized     += 1
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
        # Re-sort after penalty adjustments
        signals.sort(key=lambda s: s.confidence, reverse=True)

    # ── Intraday VWAP trend — weighted 20% factor ────────────────────────────
    # VWAP slope is ONE input, not a binary gate. It contributes 20% weight to
    # signal confidence; the strategy's own technical edge provides 80%.
    if signals and len(today) >= 12:
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
                # Remove VWAP's 20% contribution — strategy signal retains 80%
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

    # ── Confluence bonus ───────────────────────────────────────────────────────
    # When 2+ independent strategies agree on direction, this is the highest-
    # probability setup. Reward it with a confidence bonus so strong multi-
    if signals:
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

    # ── Large-session-move gate (gap / momentum-day filter) ──────────────────
    # If the session has already moved ±1.5%+ from the opening bar, it is a
    # gap or momentum day. Counter-trend entries before 13:00 ET are high-risk:
    # for continuation, and mean-reversion fades typically get run over.
    if signals and len(today) >= 2:
        _so        = float(today.iloc[0].get("open", today.iloc[0]["close"]))
        _sc        = float(today.iloc[-1]["close"])
        _sm_pct    = (_sc - _so) / max(_so, 1.0)
        _btime     = today.iloc[-1]["time"]
        _bmin      = (_btime.hour * 60 + _btime.minute) if hasattr(_btime, "hour") else 600

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

    # ── Directional consensus filter — the direction decision ────────────────
    # This is the core fix for wrong-direction trading. Three independent
    # indicators must ALL agree before a direction is considered "established":
    # "looked like" a VWAP pullback recovery.
    if signals and len(today) >= 20:
        _dc_last   = today.iloc[-1]
        _dc_rvol   = float(_dc_last.get("rvol", 1.0) or 1.0)
        _dc_close  = float(_dc_last["close"])
        _dc_vwap   = float(_dc_last.get("vwap", _dc_close) or _dc_close)

        # 1. Price position vs VWAP
        _dc_price_bull = _dc_close > _dc_vwap
        _dc_price_bear = _dc_close < _dc_vwap

        # 2. VWAP slope over 20 bars (100 min) — medium-term institutional flow
        _dc_vwap_20   = float(today.iloc[-20].get("vwap", _dc_vwap) or _dc_vwap)
        _dc_slope_pct = (_dc_vwap - _dc_vwap_20) / max(_dc_vwap_20, 1.0)
        _dc_slope_bull = _dc_slope_pct > 0.0005    # +0.05% over 100 min
        _dc_slope_bear = _dc_slope_pct < -0.0005

        # 3. Market structure (confirmed swing highs/lows)
        _dc_msa    = MarketStructureAnalyzer(today)
        _dc_trend  = _dc_msa.classify_trend()
        _dc_struct_bull = _dc_trend == "uptrend"
        _dc_struct_bear = _dc_trend == "downtrend"

        _bull_score = sum([_dc_price_bull, _dc_slope_bull, _dc_struct_bull])
        _bear_score = sum([_dc_price_bear, _dc_slope_bear, _dc_struct_bear])

        # Hard block ONLY on unanimous 3/3 — all three must agree before we fully
        # block the opposite direction. 2/3 agreement is too common on normal days
        # (price>VWAP + positive slope = 2/3 bullish almost constantly) and was
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

    # ── Quality gate 1: confidence floor ─────────────────────────────────────
    _before_floor = len(signals)
    signals = [s for s in signals if s.confidence >= _MIN_CONFIDENCE]
    if len(signals) < _before_floor:
        _dropped = _before_floor - len(signals)
        logger.info(
            "router: dropped %d low-confidence signal(s) for %s (floor=%.0f%%)",
            _dropped, ticker, _MIN_CONFIDENCE * 100,
        )

    # ── Quality gate 2: conflict veto ─────────────────────────────────────────
    # If the top two signals disagree on direction and their confidence gap is
    # within _CONFLICT_VETO_BAND, the market is sending mixed signals — skip.
    if len(signals) >= 2:
        _top, _second = signals[0], signals[1]
        if (_top.direction != _second.direction and
                (_top.confidence - _second.confidence) <= _CONFLICT_VETO_BAND):
            _db_log(
                "INFO", "scan",
                f"{ticker} — Conflict veto: {_top.strategy_id} {_top.direction} "
                f"({_top.confidence:.0%}) vs {_second.strategy_id} {_second.direction} "
                f"({_second.confidence:.0%}) within {_CONFLICT_VETO_BAND:.0%} band — "
                f"market is ambiguous, skipping both.",
            )
            logger.info(
                "router: conflict veto fired for %s (%s vs %s)",
                ticker, _top.strategy_id, _second.strategy_id,
            )
            # Annotate: conflict veto marker so chart shows the ambiguous zone
            try:
                _cv_ts = str(today.iloc[-1]["time"])
                _cv_px = float(today.iloc[-1]["close"])
                _emit_ann(ticker, "marker", "veto",
                          label=f"✗ Conflict {_top.strategy_id}↑↓{_second.strategy_id}",
                          ts=_cv_ts, price=_cv_px, color="#64748b")
            except Exception:
                pass
            return []

    # ── Volume ROC gate (false signal filter) ────────────────────────────────
    # Prevent entries when buying pressure is already fading.
    # Compares avg volume of last 3 bars vs prior 3 bars.
    if signals and len(today) >= 6:
        _recent_vol = today["volume"].iloc[-3:].mean()
        _prior_vol  = today["volume"].iloc[-6:-3].mean()
        _vol_roc    = _recent_vol / _prior_vol if _prior_vol > 0 else 1.0

        _roc_threshold = float(_get_settings().get("vol_roc_threshold", 0.50))
        if _vol_roc < _roc_threshold:
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
            # Annotate: veto marker at current price so the chart shows why no entry
            try:
                _veto_ts  = str(today.iloc[-1]["time"])
                _veto_px  = float(today.iloc[-1]["close"])
                _emit_ann(ticker, "marker", "veto",
                          label=f"✗ Vol ROC {_vol_roc:.2f}",
                          ts=_veto_ts, price=_veto_px, color="#64748b")
            except Exception:
                pass
            return []

    if signals:
        logger.info(
            "router_result: %d signal(s) for %s — top=%s %.0f%% conf",
            len(signals), ticker, signals[0].strategy_id, signals[0].confidence * 100,
        )

    # Plain-English audit (never crashes the router)
    try:
        if ticker != "SIM":
            _audit_plain_english(today, ticker, signals)
    except Exception:
        pass

    return signals


# ── Plain-English Audit ───────────────────────────────────────────────────────

_STRAT_NAMES = {
    "INST_ORB":   "Opening Range Breakout",
    "BOS_MSS":    "Break of Structure",
    "VWAP_PB":    "VWAP Pullback",
    "FVG":        "Fair Value Gap",
    "IFVG":       "Inverted Fair Value Gap",
    "MID_BRK":    "Mid-Day Breakdown",
    "AFT_REV":    "Afternoon Reversal",
    "TREND_CONT": "Trend Continuation",
    "CHAN_BREAK":  "Channel Rejection",
}


def _audit_plain_english(today: pd.DataFrame, ticker: str, signals: list) -> None:
    """
    Write plain-English structural and decision events to system_events.
    Fires only when market structure changes to avoid DB spam.
    """
    global _last_audit_state

    if len(today) < 10:
        return

    last_bar  = today.iloc[-1]
    bar_time  = last_bar["time"]
    bar_str   = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)
    rvol_now  = float(last_bar.get("rvol", 0) or 0)
    close_now = float(last_bar["close"])
    vwap_now  = float(last_bar.get("vwap", close_now) or close_now)

    msa     = MarketStructureAnalyzer(today)
    trend   = msa.classify_trend()
    highs   = msa._highs()
    lows    = msa._lows()
    last_sh = highs[-1]["price"] if highs else None
    last_sl = lows[-1]["price"]  if lows  else None

    state_key = f"{ticker}:{trend}:{last_sh}:{last_sl}"
    prev_key  = _last_audit_state.get("key", "")

    # ── 1. Structural change event ────────────────────────────────────────────
    if state_key != prev_key:
        _last_audit_state["key"] = state_key

        if trend == "downtrend":
            is_lh = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]
            is_ll = len(lows)  >= 2 and lows[-1]["price"]  < lows[-2]["price"]
            if is_lh and is_ll:
                struct_msg = (
                    f"{ticker} {bar_str} — Bearish structure confirmed. "
                    f"Lower High ${last_sh:.2f} + Lower Low ${last_sl:.2f}. "
                    f"Bot looking for SHORT/PUT entries."
                )
            elif is_lh:
                struct_msg = (
                    f"{ticker} {bar_str} — Lower High at ${last_sh:.2f}. "
                    f"Rally failed below prior peak — sellers in control. Waiting for LL confirmation."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Downtrend in progress. "
                    f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}. "
                    f"Price ${close_now:.2f} {'below' if close_now < vwap_now else 'above'} VWAP."
                )
        elif trend == "uptrend":
            is_hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]
            is_hl = len(lows)  >= 2 and lows[-1]["price"]  > lows[-2]["price"]
            if is_hh and is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Bullish structure confirmed. "
                    f"Higher High ${last_sh:.2f} + Higher Low ${last_sl:.2f}. "
                    f"Bot looking for LONG/CALL entries."
                )
            elif is_hl:
                struct_msg = (
                    f"{ticker} {bar_str} — Higher Low at ${last_sl:.2f}. "
                    f"Pullback held above prior low — buyers defending. Waiting for HH."
                )
            else:
                struct_msg = (
                    f"{ticker} {bar_str} — Uptrend in progress. "
                    f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}."
                )
        else:
            struct_msg = (
                f"{ticker} {bar_str} — Consolidating. No clear trend. "
                f"Bot waiting for breakout."
            )

        _db_log("INFO", "structure", struct_msg)

    # ── 2. RVOL advisory (log once per tier change) ───────────────────────────
    prev_rvol_tier = _last_audit_state.get("rvol_tier", "")
    cur_rvol_tier  = ("≥2.0" if rvol_now >= 2.0 else "≥1.5" if rvol_now >= 1.5
                      else "≥1.2" if rvol_now >= 1.2 else "<1.2")
    if cur_rvol_tier != prev_rvol_tier:
        _last_audit_state["rvol_tier"] = cur_rvol_tier
        if rvol_now >= 2.0:
            rvol_msg = f"{ticker} {bar_str} — Volume {rvol_now:.1f}× average. All strategies eligible."
        elif rvol_now >= 1.5:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
                f"BOS/VWAP/FVG eligible. ORB needs 2.0×."
            )
        elif rvol_now >= 1.2:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
                f"Only TREND_CONT + CHAN_BREAK eligible. Waiting for volume."
            )
        else:
            rvol_msg = (
                f"{ticker} {bar_str} — Volume low ({rvol_now:.1f}×). "
                f"No strategies eligible. Watching."
            )
        _db_log("INFO", "volume", rvol_msg)

    # ── 3. Signal fired ───────────────────────────────────────────────────────
    if signals:
        top     = signals[0]
        name    = _STRAT_NAMES.get(top.strategy_id, top.strategy_id)
        dir_txt = "PUT (short)" if top.direction == "bearish" else "CALL (long)"
        meta    = top.meta or {}

        if top.strategy_id == "INST_ORB":
            flipped = meta.get("direction_flipped", False)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}{'  [failed-breakout fade]' if flipped else ''}. "
                f"Price broke {'above' if top.direction == 'bullish' else 'below'} the opening range "
                f"with {top.rvol:.1f}× volume. Entering {dir_txt}."
            )
        elif top.strategy_id == "BOS_MSS":
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}. "
                f"Broke prior swing {'high' if top.direction == 'bullish' else 'low'}. "
                f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "TREND_CONT":
            lh_p = meta.get("lh_price") or meta.get("hl_price", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name} (re-entry). "
                f"{'LH' if top.direction == 'bearish' else 'HL'} at ${lh_p:.2f} — "
                f"trend resuming. Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        elif top.strategy_id == "CHAN_BREAK":
            proj = meta.get("projected", close_now)
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name}. "
                f"Trendline tag at ~${proj:.2f}, rejection confirmed. "
                f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
            )
        else:
            entry_msg = (
                f"{ticker} {bar_str} — ENTRY: {name} {dir_txt}. "
                f"Volume {top.rvol:.1f}×, conf {top.confidence:.0%}."
            )
        _db_log("INFO", "signal", entry_msg)

    # ── 4. No signal — log blocking reason on structural change ───────────────
    elif state_key != prev_key:
        if rvol_now < 1.2:
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Volume {rvol_now:.1f}× "
                f"(need ≥1.2× for any strategy). Watching."
            )
        elif trend == "consolidation":
            skip_msg = (
                f"{ticker} {bar_str} — No entry. Ranging — no confirmed trend. "
                f"Bot waiting for breakout."
            )
        else:
            vwap_side = "above" if close_now > vwap_now else "below"
            skip_msg = (
                f"{ticker} {bar_str} — Trend: {trend}. "
                f"Price ${close_now:.2f} ({vwap_side} VWAP). "
                f"Volume {rvol_now:.1f}×. No pattern triggered — monitoring."
            )
        _db_log("INFO", "scan", skip_msg)
