from datetime import timedelta
from functools import partial
import pandas as pd

from config.research_order_specs import SPECS
from research.engine.models import Side
from strategies.base import Signal
from strategy_health.exit_protocols import candidate_metadata
from trading.tested_strategy_research import strategy_details, _research_bars, _latest_candidate

_emitted = {}


def evaluate(frame, ticker='', execution_scope=None, now=None, *, strategy_id):
    spec = SPECS[strategy_id]
    from strategies.spy_trend_continuation_v2 import _execution_scope
    scope = _execution_scope(execution_scope)
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='America/New_York')
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert('America/New_York').tz_localize(None)
    symbol = ticker.strip().upper()
    key = (scope, symbol, strategy_id)
    if _emitted.get(key) == cutoff.floor('min'):
        return None
    if strategy_id == 'RESEARCH_FAILED_RANGE_V2':
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
        history = load_scanner_candles(symbol, broker_account_id=get_settings().get('active_broker_account_id') or None,
                                       timeframe='1Min', limit=10_000)
        source = pd.concat([history, pd.DataFrame(frame)], ignore_index=True) if not history.empty else frame
        bars = _research_bars(source, cutoff, spec.timeframe)
        if strategy_id == 'V2_GAP_FILL_RTH':
            from trading.gap_fill_history import with_history
            native = load_scanner_candles(symbol, broker_account_id=get_settings().get('active_broker_account_id') or None,
                                          timeframe='5Min', limit=1500)
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
        signal = Signal(strategy_id=strategy_id, direction='bullish' if candidate.side is Side.LONG else 'bearish',
                        confidence=.70, rvol=0.0, trigger_bar=trigger,
                        meta={**dict(candidate.features), 'underlying_stop': float(candidate.stop),
                              'underlying_target': float(candidate.target),
                              'timeframe_minutes': spec.timeframe,
                              'entry_timing': f'completed_{spec.timeframe}m_signal_then_next_quote',
                              **candidate_metadata(spec.source, engine)})
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
    policy = selected(get_settings(), strategy_id, symbol, spec.version)
    if policy:
        signal.meta['selected_test_policy'] = policy
    _emitted[key] = cutoff.floor('min')
    return signal


EVALUATORS = [(sid, partial(evaluate, strategy_id=sid)) for sid in SPECS]
