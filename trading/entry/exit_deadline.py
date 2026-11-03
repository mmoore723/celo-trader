"""Freeze replay horizon prospectively, without changing execution rules."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def capture_policy(strategy_id, broker, now):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from trading.research_session_clock import session_close_if_open
    rule = REVIEWED_STRATEGIES.get(strategy_id)
    if rule is None:
        return {'exit_deadline_capture': {'status': 'unsupported_strategy'}}
    try:
        close = session_close_if_open(broker, now)
        if close is None:
            raise ValueError('No verified open session')
        cap = min(close.astimezone(ET) - timedelta(minutes=5),
                  now.astimezone(ET).replace(hour=15, minute=55, second=0, microsecond=0))
        hold = 30 if strategy_id in ('RESEARCH_FAILED_RANGE_V2', 'RESEARCH_QQQ_TREND_V2') else rule.exit_minutes
        return {'exit_deadline_capture': {
            'status': 'awaiting_fill', 'schema_version': 1,
            'strategy_id': strategy_id, 'strategy_version': rule.version,
            'captured_at': now.isoformat(), 'session_cap': cap.isoformat(),
            'hold_minutes': hold, 'source': 'entry_time_policy_and_verified_broker_session',
        }}
    except Exception:
        return {'exit_deadline_capture': {'status': 'broker_session_unavailable'}}


def freeze_at_fill(raw_context, fill_time):
    """Only new tagged entry plans are eligible. Never infer old trade rules."""
    context = json.loads(raw_context or '{}') if isinstance(raw_context, str) else dict(raw_context or {})
    policy = context.get('exit_deadline_capture') or {}
    if policy.get('status') != 'awaiting_fill':
        return context
    try:
        selected = context.get('selected_test_policy')
        if selected is not None:
            from config.research_pair_policy import validate
            selected = validate(selected, policy['strategy_id'], selected.get('ticker'), policy['strategy_version'])
            if selected['exit_minutes'] is not None:
                policy = dict(policy, hold_minutes=selected['exit_minutes'], selected_policy_version=selected['policy_version'])
        filled = datetime.fromisoformat(str(fill_time).replace('Z', '+00:00'))
        cap = datetime.fromisoformat(policy['session_cap'])
        if filled.tzinfo is None or cap.tzinfo is None or filled >= cap:
            raise ValueError('Invalid fill/session horizon')
        deadline = cap
        if policy['hold_minutes'] is not None:
            deadline = min(cap, filled + timedelta(minutes=policy['hold_minutes']))
        context['exit_deadline'] = deadline.isoformat()
        context['exit_deadline_capture'] = dict(policy, status='captured',
                                               entry_clock=filled.isoformat())
    except (ValueError, TypeError, KeyError, OverflowError):
        context.pop('exit_deadline', None)
        context['exit_deadline_capture'] = dict(policy, status='invalid_fill_clock')
    return context
