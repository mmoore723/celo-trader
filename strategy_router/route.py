"""
strategy_router/route.py — route_signals(): the public router entry point.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Router settings are read from the package at call time so one canonical
configuration is used throughout the process.
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

from strategy_router.evaluators import ACTIVE_STRATEGIES
from strategy_router.indicator_frame import _build_indicator_frame
from trading.v2_orb_execution_profile import uses_reviewed_paid_execution_profile

logger = logging.getLogger("celo_trader.strategy_router")


def _authorized_for_order(strategy_id: object, ticker: object) -> bool:
    from config import get_settings
    from config.strategy_ticker_recommendations import is_user_authorized_ticker
    return is_user_authorized_ticker(strategy_id, ticker, get_settings())


def _candidate_key(signal: Signal) -> tuple[str, str, str]:
    """Stable identity for one candidate during a single router invocation."""
    return (
        str(getattr(signal, "strategy_id", "") or ""),
        str(getattr(signal, "direction", "") or ""),
        str(getattr(signal, "trigger_bar", "") or ""),
    )


def _remember_candidate(signal: Signal, candidate_ids: dict[tuple[str, str, str], str]) -> None:
    meta = getattr(signal, "meta", None)
    candidate_id = meta.get("shadow_candidate_id") if isinstance(meta, dict) else None
    if candidate_id:
        candidate_ids[_candidate_key(signal)] = str(candidate_id)


def _restore_candidates(
    signals: list[Signal], candidate_ids: dict[tuple[str, str, str], str]
) -> list[Signal]:
    """Keep the ledger link when a quality gate returns a copied Signal."""
    for signal in signals:
        meta = getattr(signal, "meta", None)
        if not isinstance(meta, dict):
            meta = {}
            signal.meta = meta
        if not meta.get("shadow_candidate_id"):
            candidate_id = candidate_ids.get(_candidate_key(signal))
            if candidate_id:
                meta["shadow_candidate_id"] = candidate_id
    return signals


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
    preserve_reviewed_paid_rules: bool = False,
    observation_scope: str | None = None,
    evaluation_observer=None,
    decision_recorder=None,
) -> list[Signal]:
    """
    Evaluate all strategy modules against the current bar data.

    Args:
        df                  : Multi-day 5-min OHLCV DataFrame
        ticker              : Symbol string (log context + cooldown keying)
        enabled_strategies  : Optional set of strategy IDs to run.
                              If None, all reviewed bar-close strategies run.
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
    def observe(strategy_id, status, phase='evaluation'):
        # Diagnostics get strings, never mutable signals, frames or state.
        # Quiet research replays must not populate execution coverage.
        if evaluation_observer is not None and not quiet and strategy_id in (enabled_strategies or ()):
            try:
                evaluation_observer(str(strategy_id), str(status), phase)
            except Exception:
                logger.debug('Evaluation coverage observer failed', exc_info=True)

    def capture(method, *args, **kwargs):
        if decision_recorder is not None and not quiet:
            try:
                return getattr(decision_recorder, method)(*args, **kwargs)
            except Exception:
                logger.debug('Exact decision recorder failed', exc_info=True)
        return None

    def done(result, reason):
        returned = {signal.strategy_id for signal in result}
        for sid in enabled_strategies or ():
            observe(sid, 'returned' if sid in returned else reason, 'routing')
        return result

    if df.empty or len(df) < 2:
        return done([], 'insufficient_input')
    # ``None`` explicitly means a caller wants the router's full research
    # universe. An empty set is the production safety state: no strategy has
    # earned promotion, so avoid even building indicators or emitting signals.
    _order_strategies = set(enabled_strategies or ()) if enabled_strategies is not None else None
    _observation_only = set(observation_only_strategies or ())
    # Catalog-owned research observers are incapable of execution even if a
    # caller accidentally supplies their IDs as enabled order strategies (or
    # asks for the router's full universe with ``None``).  Move them onto the
    # read-only side of the pipeline before any evaluator runs.
    from config.strategy_catalog import REVIEWED_STRATEGIES
    _catalog_observers = {
        strategy_id for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if rule.observation_only
    }
    # A catalog research rule may cross into *paper* execution only for one
    # forward-qualified ticker that this user explicitly approved. It remains
    # an observer everywhere else and can never use this path in live mode.
    _paper_promoted: set[str] = set()
    if _order_strategies:
        from config import get_settings
        from config.strategy_ticker_recommendations import is_paper_enabled_pair
        settings = get_settings()
        requested_observers = _order_strategies & _catalog_observers
        _paper_promoted = {
            strategy_id for strategy_id in requested_observers
            if is_paper_enabled_pair(strategy_id, ticker, settings)
        }
        _observation_only |= requested_observers - _paper_promoted
        _order_strategies -= requested_observers - _paper_promoted
    _catalog_observers -= _paper_promoted
    if _order_strategies is None:
        _observation_only |= _catalog_observers
    else:
        _observation_only |= _order_strategies & _catalog_observers
        _order_strategies -= _catalog_observers
    if _order_strategies is not None:
        _observation_only -= _order_strategies
    if _order_strategies is not None and not _order_strategies and not _observation_only:
        return done([], 'no_order_or_observation_strategies')

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
            return done([], 'kill_lock')

    today = prepared_today if prepared_today is not None else _build_indicator_frame(df)
    if today.empty:
        return done([], 'empty_indicator_frame')

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
    # Execution scope and research scope are deliberately different.  The
    # catalog allowlist remains absolute for order-facing strategies, while an
    # observation-only strategy is allowed to evaluate another active ticker
    # so its evidence can be measured prospectively.
    evaluators = [
        (sid, fn) for sid, fn in _all_evaluators
        if (_selected_strategies is None or sid in _selected_strategies)
        and (_authorized_for_order(sid, ticker) or sid in _observation_only)
    ]
    _selected_evaluator_ids = {sid for sid, _ in evaluators}
    for sid, _ in _all_evaluators:
        if sid in (_order_strategies or ()) and sid not in _selected_evaluator_ids:
            observe(sid, 'not_evaluated_ticker_scope')

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
            and not (preserve_reviewed_paid_rules and uses_reviewed_paid_execution_profile(sid))
            and (_order_strategies is None or sid in _order_strategies)
        ]
        if _gated:
            for sid in _gated:
                if sid not in _observation_only:
                    observe(sid, 'not_evaluated_adx_gate')
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
    if not evaluators and not injected_signals:
        return done([], 'no_eligible_evaluators_or_injected_signals')

    # Some strategies need one additional live input that a completed OHLCV
    # bar cannot express (the V2 ORB's actual quote-level retouch).  Those
    # signals are produced by the entry loop but deliberately enter here so
    # they still receive the same router gates, ranking, annotations, and
    # paper-only observation behavior as every normal evaluator.
    signals: list[Signal] = []
    candidate_ids: dict[tuple[str, str, str], str] = {}
    for sig in tuple(injected_signals or ()):
        strategy_id = str(getattr(sig, "strategy_id", "") or "").strip().upper()
        if _selected_strategies is not None and strategy_id not in _selected_strategies:
            logger.warning("Discarding disabled injected strategy %s", strategy_id)
            continue
        if not _authorized_for_order(strategy_id, ticker) and strategy_id not in _observation_only:
            logger.warning("Discarding out-of-scope injected strategy %s for %s", strategy_id, ticker)
            continue
        if candidate_observer is not None:
            try:
                candidate_observer(ticker, sig, _underlying_price)
                _remember_candidate(sig, candidate_ids)
            except Exception:
                logger.warning("candidate observer failed (non-fatal)", exc_info=True)
        if strategy_id in _observation_only:
            if observation_resolver is not None:
                try:
                    observation_resolver(sig)
                except Exception:
                    logger.warning("candidate observation resolve failed (non-fatal)", exc_info=True)
            continue
        signals.append(sig)
        if not quiet:
            try:
                _emit_signal_annotation(ticker, sig, today)
            except Exception:
                pass
    for strategy_id, fn in evaluators:
        _evaluated = False
        try:
            from trading.context_research_entries import STRATEGY_IDS as context_research_ids, evaluate as context_research
            from trading.failed_range_research import STRATEGY_ID as recovery_id, evaluate as recovery_research
            if (strategy_id in _observation_only and strategy_id == recovery_id
                    and observation_scope and observation_scope.startswith("research_worker:")):
                sig = recovery_research(today, ticker=ticker, scope=observation_scope)
            elif (strategy_id in _observation_only and strategy_id in context_research_ids
                    and observation_scope and observation_scope.startswith("research_worker:")):
                sig = context_research(today, strategy_id=strategy_id, ticker=ticker, scope=observation_scope)
            elif strategy_id in _observation_only and not _authorized_for_order(strategy_id, ticker):
                from auth.context import get_current_user_id
                from trading.cross_ticker_shadow import evaluate_bar_strategy
                sig = evaluate_bar_strategy(
                    strategy_id, fn, today, ticker=ticker,
                    account_scope=observation_scope or get_current_user_id(),
                )
            elif strategy_id in _observation_only and observation_scope:
                # Research on an authorized ticker must not consume execution
                # dedupe state (including when its switch changes mid-pass).
                sig = fn(today, ticker=ticker, execution_scope=observation_scope)
            else:
                ticket = capture('begin', strategy_id, today, ticker, fn) if (
                    strategy_id in (enabled_strategies or ()) and _authorized_for_order(strategy_id, ticker)
                ) else None
                try:
                    sig = fn(today, ticker=ticker)
                except Exception as exc:
                    capture('finish', ticket, None, error=type(exc).__name__)
                    raise
                capture('finish', ticket, sig)
            _evaluated = True
            observe(strategy_id, 'signal_returned' if sig is not None else 'no_signal_returned')
            if sig is not None:
                if candidate_observer is not None:
                    try:
                        candidate_observer(ticker, sig, _underlying_price)
                        _remember_candidate(sig, candidate_ids)
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
            observe(strategy_id, 'post_evaluation_error' if _evaluated else 'evaluation_error',
                    'routing' if _evaluated else 'evaluation')
            logger.warning("Strategy %s raised: %s", strategy_id, exc, exc_info=True)

    if not signals:
        return done([], 'no_order_signal')

    # A reviewed paid-data signal has its complete decision rule tested as one
    # unit. In either account mode, do not substitute this legacy router's
    # independent ADX/VWAP/grade/MTF/confidence/veto opinions for that rule.
    # The entry path still enforces global halt, broker data, liquidity, budget,
    # account sizing, maintenance halts, and broker execution safeguards.
    if (preserve_reviewed_paid_rules and signals
            and all(uses_reviewed_paid_execution_profile(signal.strategy_id) for signal in signals)):
        _restore_candidates(signals, candidate_ids)
        signals.sort(key=lambda signal: signal.confidence, reverse=True)
        return done(signals, 'not_returned')

    # ── Sequential quality-gate pipeline (see router_gates.py) ───────────────
    # `quiet` (added 2026-07-21 for the 1-min backtest integration) is threaded
    # into every gate that writes to the DB event log or bot.log — a bar-by-bar
    # historical replay calling this thousands of times per backtest would
    # otherwise flood the live THINKING panel with fake "in-market" narration.
    # Gating decisions themselves are IDENTICAL either way; only the logging
    # side-effects are suppressed. Never pass quiet=True on the live path.
    signals.sort(key=lambda s: s.confidence, reverse=True)

    signals = _gates.apply_session_bias_penalty(signals, today, ticker, quiet=quiet)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_vwap_weight(signals, today, ticker)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_confluence_bonus(signals, ticker, quiet=quiet)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_mtf_confirmation(signals, ticker, alpaca=alpaca, mtf_cache=mtf_cache, quiet=quiet)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_grade_filter(signals, today, ticker, quiet=quiet)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_large_move_gate(signals, today, ticker)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_directional_consensus(signals, today, ticker, quiet=quiet)
    _restore_candidates(signals, candidate_ids)
    signals = _gates.apply_confidence_floor(signals, ticker, _MIN_CONFIDENCE, quiet=quiet)
    _restore_candidates(signals, candidate_ids)

    if _gates.check_conflict_veto(signals, today, ticker, _CONFLICT_VETO_BAND, quiet=quiet):
        return done([], 'conflict_veto')
    if _gates.check_volume_roc_veto(signals, today, ticker, quiet=quiet):
        return done([], 'volume_roc_veto')

    if signals and not quiet:
        logger.info(
            "router_result: %d signal(s) for %s — top=%s %.0f%% conf",
            len(signals), ticker, signals[0].strategy_id, signals[0].confidence * 100,
        )

    return done(signals, 'not_returned_after_gates')
