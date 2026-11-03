import re
from datetime import datetime, timezone

from config.research_order_specs import SPECS, execution_id


def key(sid, ticker):
    return f'{sid}:{ticker}'


def allowed_ticker(sid, ticker, rule):
    if sid in SPECS and SPECS[sid].allowed_tickers and ticker not in SPECS[sid].allowed_tickers:
        return False
    return bool(re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}', ticker)) and (
        sid in SPECS or ticker in rule.tickers | rule.recommendation_tickers)


def active(settings, sid, ticker):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule = REVIEWED_STRATEGIES.get(sid)
    grant = (settings.get('admin_strategy_overrides') or {}).get(key(sid, ticker)) or {}
    return bool(rule and not rule.observation_only and allowed_ticker(sid, ticker, rule)
                and grant.get('enabled') is True and grant.get('strategy_version') == rule.version
                and grant.get('approved_by_admin') is True)


def tickers(settings, sid):
    return sorted({row.get('ticker') for row in (settings.get('admin_strategy_overrides') or {}).values()
                   if isinstance(row, dict) and row.get('strategy_id') == sid and row.get('ticker')
                   and active(settings, sid, row['ticker'])})


def updates(settings, source, ticker, version, enabled, actor, *, exit_minutes=None, contract_policy=None):
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    symbol = ticker.strip().upper()
    sid = execution_id(source.strip().upper(), version, symbol)
    rule = REVIEWED_STRATEGIES.get(sid)
    if rule is None or rule.version != version or rule.observation_only:
        raise ValueError('This exact research version does not have an order implementation.')
    if sid in reviewed_strategy_integrity_errors():
        raise ValueError('Execution integrity check failed. No orders enabled.')
    if not allowed_ticker(sid, symbol, rule):
        raise ValueError('This ticker is outside the implemented entry rule scope.')
    from strategy_health.closed_trade_guard import is_paused
    if enabled and is_paused(settings, sid, symbol, version):
        raise ValueError('Actual closed-trade PF pause is active for this account. Research qualification override does not change that loss control.')
    grants = dict(settings.get('admin_strategy_overrides') or {})
    grants[key(sid, symbol)] = dict(strategy_id=sid, ticker=symbol, strategy_version=version,
                                   approved_by_admin=True, approved_by=actor, enabled=bool(enabled),
                                   approved_at=datetime.now(timezone.utc).isoformat())
    if exit_minutes is not None or contract_policy is not None:
        from config.research_pair_policy import build
        grants[key(sid, symbol)]['selected_test_policy'] = build(sid, symbol, version, exit_minutes, contract_policy)
    from strategy_health.pair_recommendations import consent_scope
    pauses = dict(settings.get('strategy_pair_pauses') or {})
    pauses[consent_scope(settings, sid, symbol)] = not enabled
    result = {'admin_strategy_overrides': grants, 'strategy_pair_pauses': pauses}
    if enabled:
        result[rule.setting_key] = True
    return result
