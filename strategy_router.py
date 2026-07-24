"""
strategy_router.py — Dynamic Multi-Strategy Signal Router

Thin orchestrator: builds the indicator frame once per tick, calls each
strategy module's evaluate() function, runs the signal through the quality
gates in router_gates.py, and returns the survivors ranked by confidence.
All evaluation logic lives in strategies/; all post-evaluation filtering
lives in router_gates.py; regime classification lives in regime_manager.py.
This file only wires them together (2026-07-16 split — was 830 lines).

Strategy IDs (eight active, one OFF by default):
  GAP_GO      — strategies/gap_go.py    (09:30–09:45)  ← OFF by default, untested
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

import pandas as pd

from signals import compute_vwap_bands, compute_rvol
from risk import check_kill_lock
from trading.annotations import emit_signal_annotation as _emit_signal_annotation

# ── Re-export Signal + MSA so callers that import from strategy_router still work ─
from strategies.base import Signal, MarketStructureAnalyzer  # noqa: F401

# ── Strategy evaluator modules ────────────────────────────────────────────────
from strategies import inst_orb, bos_mss, vwap_pb, fvg, ifvg, mid_brk, aft_rev, trend_cont, chan_break, gap_go

# ── Regime classification (trend direction + trend strength) ─────────────────
from regime_manager import (
    ADX_MIN, ADX_GATED_STRATEGIES, compute_adx, compute_adx_series,  # noqa: F401 (re-exported)
)
from database import log_event as _db_log

# ── Sequential post-evaluation gates ──────────────────────────────────────────
import router_gates as _gates
from strategy_audit_log import audit_plain_english as _audit_plain_english

logger = logging.getLogger("celo_trader.strategy_router")

# ── Router quality gates ───────────────────────────────────────────────────────
# Confidence floor: strategies score 0.75 at baseline with zero bonuses.
# Anything below is a marginal signal with no meaningful edge — drop it.
_MIN_CONFIDENCE = 0.74   # confidence floor — below this is noise, not edge

# Conflict veto window: if the top two signals disagree on direction AND their
# confidence scores are within this band, the router is ambiguous — return nothing.
_CONFLICT_VETO_BAND = 0.05

# Session bias penalty fallback default — the real value is computed
# dynamically per-tick in router_gates.apply_session_bias_penalty().
_SESSION_BIAS_PENALTY = 0.05

# ── Active evaluator table (single source of truth) ───────────────────────────
# Extracted 2026-07-17 so strategy_health/engine.py can call the exact same
# raw evaluate() functions the live router uses, instead of hand-duplicating
# this list and risking drift if a strategy is added/removed/disabled here.
# NOTE: BOS_MSS intentionally absent — see module docstring.
ACTIVE_STRATEGIES = [
    ("INST_ORB",   inst_orb.evaluate),
    ("VWAP_PB",    vwap_pb.evaluate),
    ("FVG",        fvg.evaluate),
    ("IFVG",       ifvg.evaluate),
    ("MID_BRK",    mid_brk.evaluate),
    ("AFT_REV",    aft_rev.evaluate),
    ("TREND_CONT", trend_cont.evaluate),
    ("GAP_GO",     gap_go.evaluate),   # 2026-07-23, Gap 2 — see strategies/gap_go.py.
                                       # Present here (so backtester/audit tools CAN
                                       # exercise it) but gated OFF live by default via
                                       # strategy_gapgo_enabled — unlike every other
                                       # strategy in this list, it has zero backtest
                                       # history yet. Run one before flipping it on.
    # ("CHAN_BREAK", chan_break.evaluate),  # disabled — 0% WR in backtests, needs fix
]


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
      session_gap_pct — today's open vs. prior session's close, as a % —
                  added 2026-07-23 for strategies/gap_go.py (Gap 2, professional-
                  strategy-alignment audit). Constant-broadcast across every row
                  of today, same pattern as any other single-value-per-day field
                  strategies need — evaluate() only ever sees `today`, never the
                  full multi-day df, so this is computed once here where prior-day
                  data is still available, not inside the strategy itself.
    """
    if df.empty:
        return df

    latest_date = df["time"].dt.date.max()
    # BUG FIX 2026-07-22: capture today's row labels BEFORE reset_index below.
    # rvol_series (computed a few lines down) is indexed on the FULL
    # multi-day df. Previously `today` was reset to a 0-based index first,
    # then reindexed against that reset index — silently pulling whichever
    # earlier day happened to start at the same row offset instead of
    # today's real RVOL, any time df spans more than one day. Confirmed via
    # a direct call to this function on synthetic multi-day data. Affects
    # both the backtester and live (trading/entry.py's df5 is multi-day
    # after the RVOL history augment).
    today_idx   = df.index[df["time"].dt.date == latest_date]
    today       = df[df["time"].dt.date == latest_date].copy().reset_index(drop=True)

    _vwap_frame           = compute_vwap_bands(today, num_stds=(1, 2))
    today["vwap"]         = _vwap_frame["vwap"].ffill()
    today["vwap_upper1"]  = _vwap_frame["vwap_upper1"].ffill()
    today["vwap_lower1"]  = _vwap_frame["vwap_lower1"].ffill()
    today["vwap_upper2"]  = _vwap_frame["vwap_upper2"].ffill()
    today["vwap_lower2"]  = _vwap_frame["vwap_lower2"].ffill()

    rvol_series   = compute_rvol(df, lookback_days=10)
    # Positional assign via .to_numpy() — sidesteps index alignment entirely.
    # today_idx and today are in the same row order (both derived from the
    # same boolean mask, mask application preserves order), so this is safe.
    today["rvol"] = rvol_series.reindex(today_idx).fillna(1.0).to_numpy()

    today["ema50"] = today["close"].ewm(span=50, adjust=False).mean()

    hl  = today["high"]  - today["low"]
    hcp = (today["high"]  - today["close"].shift(1)).abs()
    lcp = (today["low"]   - today["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    today["atr"] = tr.ewm(span=14, adjust=False).mean()

    today["vol_sma20"] = today["volume"].rolling(100, min_periods=20).mean()

    # ── Session gap % (constant-broadcast) ────────────────────────────────
    _prior_mask = df["time"].dt.date < latest_date
    if _prior_mask.any() and len(today) > 0:
        _prior_close = float(df.loc[_prior_mask].iloc[-1]["close"])
        _today_open  = float(today.iloc[0]["open"])
        today["session_gap_pct"] = ((_today_open - _prior_close) / _prior_close * 100.0
                                     if _prior_close else 0.0)
    else:
        today["session_gap_pct"] = 0.0   # no prior-day data (e.g. synthetic/short backtest window)

    return today


# ── Public router ─────────────────────────────────────────────────────────────

def route_signals(
    df: pd.DataFrame,
    ticker: str,
    enabled_strategies: "set[str] | None" = None,
    quiet: bool = False,
    alpaca=None,
    mtf_cache: "dict | None" = None,
) -> list[Signal]:
    """
    Evaluate all strategy modules against the current bar data.

    Args:
        df                  : Multi-day 5-min OHLCV DataFrame
        ticker              : Symbol string (log context + cooldown keying)
        enabled_strategies  : Optional set of strategy IDs to run.
                              If None, all eight run.
        quiet               : If True, skip the "bar_eval" DB narration
                              (e.g. the ADX chop-regime notice) written via
                              _db_log(). Used by strategy_health/engine.py's
                              historical replay so a nightly audit doesn't
                              write hundreds of bar-by-bar rows into the same
                              event log the live THINKING panel reads from.
                              Never set True on the live trading path.
        alpaca, mtf_cache   : Optional — only the live call site in
                              trading/entry.py passes these. When both are
                              given, router_gates.apply_mtf_confirmation()
                              applies a soft 1Hour-bias confidence adjustment
                              (see trading/mtf_live_gate.py). Every other
                              caller (backtester, audit tools) leaves these
                              None and gets identical behavior to before
                              2026-07-23 — this is a strictly additive,
                              opt-in change.

    Returns:
        list[Signal] sorted by confidence descending (may be empty).
    """
    if df.empty or len(df) < 2:
        return []

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

    # Evaluator table — each module's evaluate() self-gates on its own session
    # window. See ACTIVE_STRATEGIES above (single source of truth).
    _all_evaluators = ACTIVE_STRATEGIES
    evaluators = (
        [(sid, fn) for sid, fn in _all_evaluators if sid in enabled_strategies]
        if enabled_strategies is not None
        else _all_evaluators
    )

    # ── ADX trend-strength gate — skip breakout strategies in chop (< 25) ────
    # Fail-open: if ADX can't be computed (thin data), no strategies are gated.
    _adx_now = compute_adx(df)
    if _adx_now is not None and _adx_now < ADX_MIN:
        _gated = [sid for sid, _ in evaluators if sid in ADX_GATED_STRATEGIES]
        if _gated:
            evaluators = [(sid, fn) for sid, fn in evaluators
                          if sid not in ADX_GATED_STRATEGIES]
            if not quiet:
                try:
                    _db_log("INFO", "bar_eval",
                            f"⚪ [{ticker}] ADX {_adx_now:.0f} < {ADX_MIN:.0f} — chop regime. "
                            f"Breakout strategies gated: {', '.join(_gated)}. "
                            f"Mean-reversion strategies still active.")
                except Exception:
                    pass
    if not evaluators:
        return []

    signals: list[Signal] = []
    for strategy_id, fn in evaluators:
        try:
            sig = fn(today, ticker=ticker)   # ticker= needed for cooldown tracking
            if sig is not None:
                signals.append(sig)
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

    # ── Sequential quality-gate pipeline (see router_gates.py) ───────────────
    # `quiet` (added 2026-07-21 for the 1-min backtest integration) is threaded
    # into every gate that writes to the DB event log or bot.log — a bar-by-bar
    # historical replay calling this thousands of times per backtest would
    # otherwise flood the live THINKING panel with fake "in-market" narration.
    # Gating decisions themselves are IDENTICAL either way; only the logging
    # side-effects are suppressed. Never pass quiet=True on the live path.
    signals = _gates.apply_regime_gate(signals, df, ticker, quiet=quiet)
    signals.sort(key=lambda s: s.confidence, reverse=True)

    signals = _gates.apply_session_bias_penalty(signals, today, ticker, quiet=quiet)
    signals = _gates.apply_vwap_weight(signals, today, ticker)
    signals = _gates.apply_confluence_bonus(signals, ticker, quiet=quiet)
    signals = _gates.apply_mtf_confirmation(signals, ticker, alpaca=alpaca, mtf_cache=mtf_cache, quiet=quiet)
    signals = _gates.apply_large_move_gate(signals, today, ticker)
    signals = _gates.apply_directional_consensus(signals, today, ticker, quiet=quiet)
    signals = _gates.apply_confidence_floor(signals, ticker, _MIN_CONFIDENCE)

    if _gates.check_conflict_veto(signals, today, ticker, _CONFLICT_VETO_BAND, quiet=quiet):
        return []
    if _gates.check_volume_roc_veto(signals, today, ticker, quiet=quiet):
        return []

    if signals and not quiet:
        logger.info(
            "router_result: %d signal(s) for %s — top=%s %.0f%% conf",
            len(signals), ticker, signals[0].strategy_id, signals[0].confidence * 100,
        )

    try:
        if ticker != "SIM" and not quiet:
            _audit_plain_english(today, ticker, signals)
    except Exception:
        pass

    return signals
