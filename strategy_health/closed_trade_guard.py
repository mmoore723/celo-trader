from datetime import datetime, timezone
from math import isfinite


def scope(settings, sid, ticker, version):
    mode = 'paper' if settings.get('paper_trading', True) else 'live'
    return f"{mode}:{settings.get('active_broker_account_id') or ''}:{sid}:{ticker}:{version}"


def is_paused(settings, sid, ticker, version):
    return bool((settings.get('strategy_closed_trade_pauses') or {}).get(scope(settings, sid, ticker, version)))


def enforce():
    from config import get_settings, get_user_data_dir, save_settings
    from config.atomic_files import _lock_for
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from strategy_health.closed_trade_evidence import build_closed_trade_evidence

    initial = get_settings()
    if not initial.get('active_broker_account_id'):
        return []
    evidence = build_closed_trade_evidence()
    if not evidence.get('available'):
        return []
    with _lock_for(get_user_data_dir() / 'settings.json'):
        settings = get_settings()
        if (settings.get('active_broker_account_id'), settings.get('paper_trading', True)) != (initial.get('active_broker_account_id'), initial.get('paper_trading', True)):
            return []
        pauses = dict(settings.get('strategy_closed_trade_pauses') or {})
        added = []
        for strategy in evidence['strategies']:
            sid = strategy['strategy_id']
            rule = REVIEWED_STRATEGIES.get(sid)
            if not rule or strategy['version'] != rule.version:
                continue
            for pair in strategy['pairs']:
                gains, losses = pair.get('gross_profit'), pair.get('gross_loss')
                if not pair.get('completed_trades') or not isinstance(gains, (int, float)) or not isinstance(losses, (int, float)):
                    continue
                if not isfinite(gains) or not isfinite(losses) or not 0 <= gains < losses:
                    continue
                key = scope(settings, sid, pair['ticker'], rule.version)
                if key in pauses:
                    continue
                pauses[key] = {'reason': 'Closed trade PF below 1',
                               'profit_factor': pair['profit_factor'],
                               'completed_trades': pair['completed_trades'],
                               'realized_pnl': pair['realized_pnl'],
                               'paused_at': datetime.now(timezone.utc).isoformat()}
                added.append(key)
        if added:
            save_settings({'strategy_closed_trade_pauses': pauses})
        return added
