"""QQQ-only entry-frozen setup protection before profit activation."""
import json
import math
from datetime import timedelta
from strategy_health.premium_rules import clock, quote_validation
SPEC = {'timeframe_minutes': 5, 'consecutive_candles': 1}
REASON = 'chart_invalidation_1x5m'
PAIR = ('RESEARCH_QQQ_TREND_V2', 'QQQ')

def validate(policy):
    spec = policy.get('chart_invalidation_exit')
    if spec is not None and (spec != SPEC or policy.get('adverse_candle_failsafe') is not None
            or not policy.get('replace_native_exit')
            or (policy.get('strategy'), policy.get('ticker')) != PAIR):
        raise ValueError('Invalid approved chart-invalidation exit')
    return spec

def check(trade, frame, now):
    context = trade.get('strategy_context_json') or {}
    context = json.loads(context) if isinstance(context, str) else context
    level = context.get('v2_stop')
    try:
        if isinstance(level, bool) or not math.isfinite(float(level)) or float(level) <= 0:
            raise ValueError()
        level = float(level)
    except (TypeError, ValueError):
        return {'status': 'original_setup_level_unavailable'}
    current = clock(now)
    end = current.replace(minute=current.minute // 5 * 5, second=0, microsecond=0)
    start = end - timedelta(minutes=5)
    if start < clock(trade['entry_time']):
        return {'status': 'waiting_for_full_post_entry_candle'}
    if trade.get('option_type') not in ('call', 'put'):
        return {'status': 'option_direction_unavailable'}
    if frame is None or frame.empty or 'time' not in frame or 'close' not in frame:
        return {'status': 'completed_5m_candle_unavailable'}
    try:
        rows = [row for _, row in frame.iterrows() if clock(row['time']) == start]
        if len(rows) != 1:
            return {'status': 'latest_completed_5m_candle_missing_or_duplicate'}
        close = float(rows[0]['close'])
        if not math.isfinite(close) or close <= 0:
            raise ValueError()
        broken = close < level if trade['option_type'] == 'call' else close > level
        return {'status': 'setup_broken' if broken else 'setup_intact', 'broken': broken,
                'original_setup_level': level, 'close': close, 'bar_start': start.isoformat(),
                'bar_closed_at': end.isoformat(), 'evaluated_at': current.isoformat()}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {'status': 'invalid_5m_candle'}

def apply(state, *, trade, quantity, sold, quote, now, frame):
    out = dict(state)
    if out.get('chart_exit_signal'):
        return out, (True, REASON)
    if out.get('activated') or sold > 0:
        out['chart_exit_status'] = 'disabled_after_profit_activation'
        return out, None
    result = check(trade, frame, now)
    out['chart_exit_check'] = result
    q, validation = quote_validation(quote, now, quantity, trade['contract_symbol'])
    out['chart_exit_quote_check'] = validation
    if not q:
        out['chart_exit_status'] = 'waiting_for_fresh_sized_option_bid'
        return out, None
    out['chart_exit_status'] = 'triggered' if result.get('broken') else 'monitoring'
    if result.get('broken'):
        out['chart_exit_signal'] = {**q, 'reason': REASON, 'candle': result}
        return out, (True, REASON)
    return out, None
