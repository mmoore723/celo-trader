from datetime import timedelta
from functools import partial
import pandas as pd

from config.research_order_specs import SPECS
from research.engine.models import Side
from strategies.base import Signal
from strategy_health.exit_protocols import candidate_metadata
from trading.tested_strategy_research import strategy_details, _research_bars, _latest_candidate

_emitted = {}
_episode_state = {}


def evaluate(frame, ticker='', execution_scope=None, now=None, *, strategy_id):
    spec = SPECS[strategy_id]
    from strategies.spy_trend_continuation_v2 import _execution_scope
    scope = _execution_scope(execution_scope)
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='America/New_York')
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert('America/New_York').tz_localize(None)
    symbol = ticker.strip().upper()
    if spec.allowed_tickers and symbol not in spec.allowed_tickers:
        return None
    key = (scope, symbol, strategy_id)
    if _emitted.get(key) == cutoff.floor('min'):
        return None
    if spec.adapter == 'retouch':
        return None  # Live quote path calls finalize() from injected_setups.
    if strategy_id.startswith('APPROVED_') and spec.adapter == 'library':
        # Use the research evaluator itself, including warmup and frozen exit
        # state. Execution has its own dedupe scope and accepts only a fresh signal.
        from database import load_scanner_candles
        from config import get_settings
        from broker.shared_market import FEED_POLICY
        from trading.tested_strategy_research import evaluate_tested_research
        account = get_settings().get('active_broker_account_id') or None
        def history_for(tf):
            return load_scanner_candles(symbol, broker_account_id=account,
                                       timeframe=tf, limit=10000, required_source=FEED_POLICY)
        history = history_for('1Min')
        prices = pd.concat([history, pd.DataFrame(frame)], ignore_index=True) if not history.empty else frame
        candidates = evaluate_tested_research(prices, symbol, [spec.source],
            scope='approved_order:' + scope + ':' + strategy_id, now=cutoff,
            history_5m=history_for('5Min') if spec.source == 'V2_EMA_PULLBACK_RTH' else None,
            history_15m=history_for('15Min') if spec.source == 'V2_EMA_PULLBACK_RTH' else None)
        signal = candidates[0] if candidates else None
        if signal is not None:
            trigger = pd.Timestamp(signal.trigger_bar)
            if not trigger <= cutoff < trigger + timedelta(minutes=1):
                return None
    elif spec.adapter == 'two_leg':
        from trading.two_leg_research import update
        signal, _ = update(_episode_state, frame, ticker=symbol, now=cutoff,
                           scope='research_worker:approved_order:' + scope)
    elif spec.adapter == 'context':
        from trading.context_research_entries import evaluate as native
        from strategy_health.context_orb_exit import metadata as orb_metadata
        from strategy_health.context_vwap_exit import metadata as vwap_metadata
        signal = native(frame, strategy_id=spec.source, ticker=symbol,
                        scope='research_worker:approved_order:' + scope, now=cutoff)
        if signal is not None:
            signal.meta.update(orb_metadata(spec.source))
            signal.meta.update(vwap_metadata(spec.source))
    elif spec.adapter == 'squeeze':
        from strategies.context_strategy_observers import evaluate_squeeze_macd
        from strategy_health.squeeze_exit import metadata
        signal = evaluate_squeeze_macd(frame, ticker='QQQ',
                    execution_scope='approved_squeeze:' + scope + ':' + symbol, now=cutoff)
        if signal is not None:
            signal.meta.update(metadata(spec.source))
    elif spec.adapter == 'native_fvg':
        from strategies.spy_afternoon_fvg_v2 import evaluate as native
        signal = native(frame, ticker='SPY', execution_scope='approved_fvg:' + scope + ':' + symbol, now=cutoff)
    elif strategy_id == 'RESEARCH_QQQ_TREND_V2' or spec.adapter == 'native_trend':
        from strategies.spy_trend_continuation_v2 import evaluate as native
        # Identical native engine and real QQQ bars, as in the research shadow.
        # The alias passes the unchanged SPY guard; actual orders retain QQQ.
        signal = native(frame, ticker='SPY', execution_scope='approved_qqq_trend:' + scope + ':' + symbol)
        if signal is not None:
            signal.meta.update(underlying_stop=signal.meta['v2_stop'], underlying_target=signal.meta['v2_target'],
                               timeframe_minutes=5)
    elif strategy_id == 'RESEARCH_FAILED_RANGE_V2':
        from trading.failed_range_research import evaluate as native
        signal = native(frame, ticker=symbol, scope='research_worker:approved_order:' + scope, now=cutoff)
    elif strategy_id == 'RESEARCH_CTX_ORB_ATR10_V2':
        from trading.context_research_entries import evaluate as native
        from strategy_health.context_orb_exit import metadata
        signal = native(frame, strategy_id=spec.source, ticker=symbol,
                        scope='research_worker:approved_order:' + scope, now=cutoff)
        if signal is not None:
            signal.meta.update(metadata(spec.source))
    else:
        library = strategy_details(spec.source)
        if library is None or library.version != spec.version:
            return None
        from database import load_scanner_candles
        from config import get_settings
        from broker.shared_market import FEED_POLICY
        history = load_scanner_candles(symbol, broker_account_id=get_settings().get('active_broker_account_id') or None,
                                       timeframe='1Min', limit=10_000, required_source=FEED_POLICY)
        source = pd.concat([history, pd.DataFrame(frame)], ignore_index=True) if not history.empty else frame
        bars = _research_bars(source, cutoff, spec.timeframe)
        if strategy_id == 'V2_GAP_FILL_RTH':
            from trading.gap_fill_history import with_history
            native = load_scanner_candles(symbol, broker_account_id=get_settings().get('active_broker_account_id') or None,
                                          timeframe='5Min', limit=1500, required_source=FEED_POLICY)
            bars = with_history(bars, native, cutoff)
        if not bars:
            return None
        engine = library.factory()
        candidate = _latest_candidate(engine, bars, research_strategy_id=spec.source)
        if candidate is None or (library.allowed_sides is not None and candidate.side not in library.allowed_sides):
            return None
        trigger = pd.Timestamp(candidate.timestamp) + timedelta(minutes=spec.timeframe)
        if not trigger <= cutoff < trigger + timedelta(minutes=1):
            return None
        from strategy_health.structural_capture import entry_levels
        signal = Signal(strategy_id=strategy_id, direction='bullish' if candidate.side is Side.LONG else 'bearish',
                        confidence=.70, rvol=0.0, trigger_bar=trigger,
                        meta={**dict(candidate.features), 'underlying_stop': float(candidate.stop),
                              **entry_levels(spec.source, candidate, bars, engine, spec.timeframe),
                              'underlying_target': float(candidate.target),
                              'timeframe_minutes': spec.timeframe,
                              'entry_timing': f'completed_{spec.timeframe}m_signal_then_next_quote',
                              **candidate_metadata(spec.source, engine)})
    signal = finalize(signal, strategy_id, symbol)
    if signal is not None:
        _emitted[key] = cutoff.floor('min')
    return signal


def finalize(signal, strategy_id, symbol):
    """Freeze exact ticker configuration on a signal, without granting consent."""
    spec = SPECS[strategy_id]
    if signal is None:
        return None
    if signal.meta.get('strategy_version', spec.version) != spec.version:
        return None
    signal.strategy_id = strategy_id
    signal.meta.update(strategy_version=spec.version, research_source_strategy_id=spec.source,
                       research_order_route='exact_research_v1', observation_only=False)
    signal.meta.pop('research_library', None)
    from config import get_settings
    from config.research_pair_policy import selected
    settings = get_settings()
    from config.admin_strategy_overrides import key
    from strategy_health.pair_recommendations import consent_scope
    grant = ((settings.get('admin_strategy_overrides') or {}).get(key(strategy_id, symbol))
             or (settings.get('strategy_pair_approvals') or {}).get(consent_scope(settings, strategy_id, symbol)) or {})
    if grant.get('ticker_config'):
        from copy import deepcopy
        signal.meta['approved_ticker_config'] = deepcopy(grant['ticker_config'])
    policy = selected(settings, strategy_id, symbol, spec.version)
    if policy:
        signal.meta['selected_test_policy'] = policy
    return signal


EVALUATORS = [(sid, partial(evaluate, strategy_id=sid)) for sid in SPECS if SPECS[sid].adapter != 'retouch']
