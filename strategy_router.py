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

  BOS_MSS (strategies/bos_mss.py) — DISABLED.
  Liquidity sweep detection (the core BOS_MSS gate) was merged into FVG as a
  soft confidence modifier. FVG with a confirmed prior-swing sweep fires at up
  to 0.90 confidence; without a sweep it fires at up to 0.75. Running both as
  separate evaluators was redundant — a BOS creates the FVG, so they were
  double-voting on the same institutional move.

All signals pass through RiskManager gates in risk.py before entry:
  • 1% risk rule  • 1.6 R:R minimum  • 20% hard stop  • time-box exit

Changes vs. pre-refactor strategy_router.py
────────────────────────────────────────────
• Each _eval_* function moved to its own module under strategies/
• Shared primitives (Signal, MSA, RVOL helpers) live in strategies/base.py
• INST_ORB + BOS_MSS include: per-ticker cooldown, MFE gate, VWAP flip fix
• route_signals() now passes ticker= to each evaluator (needed for cooldown)
• This file is now < 200 lines; easy to read and change
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

# ── Re-export Signal + MSA so callers that import from strategy_router still work ─
from strategies.base import Signal, MarketStructureAnalyzer  # noqa: F401

# ── Strategy evaluator modules ────────────────────────────────────────────────
from strategies import inst_orb, bos_mss, vwap_pb, fvg, mid_brk, aft_rev, trend_cont, chan_break

logger = logging.getLogger("celo_trader.strategy_router")

# ── Router quality gates ───────────────────────────────────────────────────────
# Confidence floor: strategies score 0.75 at baseline with zero bonuses.
# Anything ≤ 0.77 is a marginal signal with no meaningful RVOL/body/recency edge —
# drop it rather than picking "best of weak."
_MIN_CONFIDENCE = 0.78

# Conflict veto window: if the top two signals disagree on direction AND their
# confidence scores are within this band, the router is ambiguous — return nothing.
_CONFLICT_VETO_BAND = 0.05

# Session bias penalty: applied when a signal goes against the session's own
# price action (close is BOTH below the open AND below VWAP for bearish session,
# or BOTH above open AND VWAP for bullish session). This is not a direction block
# — it's a confidence tax. Strong setups still clear the 0.78 floor after the
# penalty; marginal counter-session signals get naturally filtered out.
_SESSION_BIAS_PENALTY = 0.05

# ── Audit state — tracks last-logged structure so we don't spam the DB ────────
_last_audit_state: dict = {}


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
    # NOTE: BOS_MSS is intentionally absent. Its liquidity sweep detection was
    # merged into FVG as a confidence modifier (see strategies/fvg.py). Keeping
    # both active caused double-voting on the same institutional move — a break
    # of structure IS what creates the fair value gap.
    _all_evaluators = [
        ("INST_ORB",   inst_orb.evaluate),
        ("VWAP_PB",    vwap_pb.evaluate),
        ("FVG",        fvg.evaluate),
        ("MID_BRK",    mid_brk.evaluate),
        ("AFT_REV",    aft_rev.evaluate),
        ("TREND_CONT", trend_cont.evaluate),
        ("CHAN_BREAK",  chan_break.evaluate),
    ]
    evaluators = (
        [(sid, fn) for sid, fn in _all_evaluators if sid in enabled_strategies]
        if enabled_strategies is not None
        else _all_evaluators
    )

    for strategy_id, fn in evaluators:
        try:
            # Pass ticker= so cooldown tracking and log context work correctly.
            sig = fn(today, ticker=ticker)
            if sig is not None:
                signals.append(sig)
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
    # VWAP is intentionally excluded — individual strategies already gate on VWAP,
    # so using it here is redundant and creates a no-op for strategies that require
    # close > vwap (VWAP_PB bullish can never also have close < vwap).
    # Session open is new information: none of the strategies check whether price
    # is above or below where the day STARTED. If we've given up the opening level,
    # the session character is bearish regardless of short-term VWAP positioning.
    #   Bearish session: close < session_open → bullish signals penalized
    #   Bullish session: close > session_open → bearish signals penalized
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
            for _sig in signals:
                _counter = (
                    (_session_bearish and _sig.direction == "bullish") or
                    (_session_bullish and _sig.direction == "bearish")
                )
                if _counter:
                    _old_conf       = _sig.confidence
                    _sig.confidence = max(0.0, _sig.confidence - _SESSION_BIAS_PENALTY)
                    _penalized     += 1
                    logger.debug(
                        "router: session_bias=%s penalized %s %s conf %.2f→%.2f",
                        _bias_label, _sig.strategy_id, _sig.direction,
                        _old_conf, _sig.confidence,
                    )
            if _penalized:
                _db_log(
                    "INFO", "scan",
                    f"{ticker} — Session bias={_bias_label}: "
                    f"{_penalized} counter-session signal(s) penalized -{_SESSION_BIAS_PENALTY:.0%} "
                    f"(close={_curr_close:.2f} vs session_open={_session_open:.2f})",
                )
        # Re-sort after penalty adjustments
        signals.sort(key=lambda s: s.confidence, reverse=True)

    # ── Quality gate 1: confidence floor ─────────────────────────────────────
    # Drop signals that barely clear the baseline (no meaningful edge).
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
