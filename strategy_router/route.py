"""
strategy_router/route.py — route_signals(): the public router entry point.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

A/B-test knob note: _MIN_CONFIDENCE and ADX_GATED_STRATEGIES are read via a
live dotted lookup on the package object (`_pkg.ATTR`) at the top of
route_signals(), NOT via a plain module-level global defined in this file.
Two archived A/B test scripts monkey-patch these directly on the PACKAGE
object before calling route_signals():
  - scripts/ab_tests/ab_test_confidence_floor.py does
    `strategy_router._MIN_CONFIDENCE = floor`
  - scripts/ab_tests/ab_test_mid_brk_adx_gate.py does
    `strategy_router.ADX_GATED_STRATEGIES = _orig - {"MID_BRK"}`
Both scripts expect that mutation to actually change route_signals()'s
behavior. In the original single-file module, a bare global name inside a
function always resolved against ITS OWN module's current namespace at call
time — since `strategy_router` WAS that module, the monkey-patch worked
automatically. Now that route_signals() lives in a submodule
(strategy_router/route.py) separate from the package's own namespace
(strategy_router/__init__.py, i.e. what `import strategy_router` gives you),
a `from ... import ATTR`-style binding captured once at import time would
never see a later `strategy_router.ATTR = value` mutation. The live dotted
lookup at the top of the function reproduces the original semantics exactly.
See strategy_router/__init__.py's docstring for where the canonical values
of _MIN_CONFIDENCE and ADX_GATED_STRATEGIES now live.
"""

from __future__ import annotations

import logging

import pandas as pd

from risk import check_kill_lock
from trading.annotations import emit_signal_annotation as _emit_signal_annotation
from strategies.base import Signal
from regime_manager import ADX_MIN, compute_adx
from database import log_event as _db_log
import router_gates as _gates
from strategy_audit_log import audit_plain_english as _audit_plain_english

from strategy_router.evaluators import ACTIVE_STRATEGIES
from strategy_router.indicator_frame import _build_indicator_frame

logger = logging.getLogger("celo_trader.strategy_router")


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

    # Live dotted lookup on the package namespace — see module docstring for
    # why this can't be a plain module-level global in this file.
    import strategy_router as _pkg
    _MIN_CONFIDENCE       = _pkg._MIN_CONFIDENCE
    ADX_GATED_STRATEGIES  = _pkg.ADX_GATED_STRATEGIES
    _CONFLICT_VETO_BAND   = _pkg._CONFLICT_VETO_BAND

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
    # window. See ACTIVE_STRATEGIES (single source of truth).
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
    signals = _gates.apply_grade_filter(signals, today, ticker, quiet=quiet)
    signals = _gates.apply_large_move_gate(signals, today, ticker)
    signals = _gates.apply_directional_consensus(signals, today, ticker, quiet=quiet)
    signals = _gates.apply_confidence_floor(signals, ticker, _MIN_CONFIDENCE, quiet=quiet)

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
