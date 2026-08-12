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
    prepared_today: "pd.DataFrame | None" = None,
    adx_now: "float | None" = None,
    candidate_observer=None,
    observation_only_strategies: "set[str] | None" = None,
    observation_resolver=None,
    injected_signals: "list[Signal] | None" = None,
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
        prepared_today      : Optional already-augmented current-session
                              frame. Backtests use this to reuse causal
                              indicator values prepared once per session;
                              live callers leave it unset.
        observation_only_strategies : Optional strategy IDs to evaluate only
                              for paper evidence. Their raw signals are sent
                              to ``candidate_observer`` then resolved through
                              ``observation_resolver``; they are excluded
                              before all order-facing gates and never returned.

    Returns:
        list[Signal] sorted by confidence descending (may be empty).
    """
    if df.empty or len(df) < 2:
        return []
    # ``None`` explicitly means a caller wants the router's full research
    # universe. An empty set is the production safety state: no strategy has
    # earned promotion, so avoid even building indicators or emitting signals.
    _order_strategies = set(enabled_strategies or ()) if enabled_strategies is not None else None
    _observation_only = set(observation_only_strategies or ())
    if _order_strategies is not None:
        _observation_only -= _order_strategies
    if _order_strategies is not None and not _order_strategies and not _observation_only:
        return []

    # Live dotted lookup on the package namespace — see module docstring for
    # why this can't be a plain module-level global in this file.
    import strategy_router as _pkg
    _MIN_CONFIDENCE       = _pkg._MIN_CONFIDENCE
    ADX_GATED_STRATEGIES  = _pkg.ADX_GATED_STRATEGIES
    _CONFLICT_VETO_BAND   = _pkg._CONFLICT_VETO_BAND

    # Historical replays must not depend on a present-day live kill switch.
    # Besides making a backtest non-deterministic, the check is a DB read on
    # every one-minute bar.  The live order path still always performs it.
    if not quiet:
        _killed, _kill_reason = check_kill_lock()
        if _killed:
            logger.warning(
                "route_signals blocked by kill lock",
                extra={"event": "kill_lock_blocked", "reason": _kill_reason, "ticker": ticker},
            )
            return []

    today = prepared_today if prepared_today is not None else _build_indicator_frame(df)
    if today.empty:
        return []

    _underlying_price = None
    try:
        _underlying_price = float(today["close"].iloc[-1])
    except Exception:
        pass
    if candidate_observer is not None:
        try:
            # Same callback module resolves due candidates before this bar's
            # new signals are stored. It is observational and non-fatal.
            from shadow_ledger import resolve_due_directional_outcomes
            resolve_due_directional_outcomes(ticker, _underlying_price)
        except Exception:
            logger.warning("candidate outcome observer failed (non-fatal)", exc_info=True)

    # Evaluator table — each module's evaluate() self-gates on its own session
    # window. See ACTIVE_STRATEGIES (single source of truth).
    _all_evaluators = ACTIVE_STRATEGIES
    _selected_strategies = None if _order_strategies is None else _order_strategies | _observation_only
    evaluators = (
        [(sid, fn) for sid, fn in _all_evaluators if sid in _selected_strategies]
        if _selected_strategies is not None else _all_evaluators
    )

    # ── ADX trend-strength gate — skip breakout strategies in chop (< 25) ────
    # Fail-open: if ADX can't be computed (thin data), no strategies are gated.
    _adx_now = adx_now if adx_now is not None else compute_adx(df)
    if _adx_now is not None and _adx_now < ADX_MIN:
        # An observation-only strategy must still be evaluated before this
        # gate so the learning ledger can answer whether ADX helped or hurt.
        # The same signal is removed before the order-facing pipeline below.
        _gated = [
            sid for sid, _ in evaluators
            if sid in ADX_GATED_STRATEGIES
            and (_order_strategies is None or sid in _order_strategies)
        ]
        if _gated:
            evaluators = [
                (sid, fn) for sid, fn in evaluators
                if sid in _observation_only or sid not in _gated
            ]
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

    # Some strategies need one additional live input that a completed OHLCV
    # bar cannot express (the V2 ORB's actual quote-level retouch).  Those
    # signals are produced by the entry loop but deliberately enter here so
    # they still receive the same router gates, ranking, annotations, and
    # paper-only observation behavior as every normal evaluator.
    signals: list[Signal] = list(injected_signals or [])
    for sig in tuple(signals):
        if candidate_observer is not None:
            try:
                candidate_observer(ticker, sig, _underlying_price)
            except Exception:
                logger.warning("candidate observer failed (non-fatal)", exc_info=True)
        if not quiet:
            try:
                _emit_signal_annotation(ticker, sig, today)
            except Exception:
                pass
    for strategy_id, fn in evaluators:
        try:
            sig = fn(today, ticker=ticker)   # ticker= needed for cooldown tracking
            if sig is not None:
                if candidate_observer is not None:
                    try:
                        candidate_observer(ticker, sig, _underlying_price)
                    except Exception:
                        logger.warning("candidate observer failed (non-fatal)", exc_info=True)
                if strategy_id in _observation_only:
                    if observation_resolver is not None:
                        try:
                            observation_resolver(sig)
                        except Exception:
                            logger.warning("candidate observation resolve failed (non-fatal)", exc_info=True)
                    # Do not annotate, gate, rank, select a contract, or
                    # return an observation-only candidate to the entry loop.
                    continue
                signals.append(sig)
                # Annotations are live-dashboard side effects.  Suppress
                # them during a quiet historical replay so an A/B test does
                # not create live chart records or perform DB writes.
                if not quiet:
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
