import json
import logging
from datetime import time

from fastapi import HTTPException


def trading_tickers(settings):
    """Current execution permissions, never the research/discovery universe."""
    from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids
    from config.admin_strategy_overrides import tickers as override_tickers
    candidates = set()
    for sid, rule in REVIEWED_STRATEGIES.items():
        candidates.update(rule.tickers | rule.recommendation_tickers)
        candidates.update(override_tickers(settings, sid))
    candidates.update(row['ticker'] for row in (settings.get('strategy_pair_approvals') or {}).values()
                      if isinstance(row, dict) and row.get('ticker'))
    return sorted(ticker for ticker in candidates
                  if enabled_reviewed_strategy_ids(settings, ticker=ticker))


def _path():
    from config import get_user_data_dir
    return get_user_data_dir(create=False) / 'daily_brief.json'


def _saved():
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def read_report():
    from database import _now_et
    from config import get_settings
    saved = _saved()
    if saved.get('date') != _now_et().date().isoformat():
        raise HTTPException(503, 'Today\'s brief is not ready. Preparation starts at 9:00 AM ET, without opening this page.', headers={'Retry-After': '60'})
    allowed = set(trading_tickers(get_settings()))
    return [{**row, 'prepared_at': saved['prepared_at']} for row in saved['rows']
            if row.get('ticker') in allowed]


def prepare():
    from database import _now_et
    from config import get_api_keys, get_settings
    from config.atomic_files import atomic_write_json
    from api.routes.market import build_premarket_report
    now = _now_et()
    saved = _saved()
    allowed = trading_tickers(get_settings())
    if now.time() < time(9):
        return
    if saved.get('date') == now.date().isoformat() and set(allowed).issubset(
            {row.get('ticker') for row in saved.get('rows', [])}):
        return
    keys = get_api_keys()
    if not any(keys.get(key) for key in ('alpaca_api_key', 'tradier_api_key', 'tradier_market_api_key')):
        return
    rows = build_premarket_report('')
    if not rows or not any(row.get('price', 0) > 0 for row in rows):
        return
    atomic_write_json(_path(), {'date': now.date().isoformat(), 'prepared_at': _now_et().isoformat(), 'rows': rows})


def refresh_once(stop):
    from auth.context import set_current_user
    from auth.users import list_users
    try:
        for user in list_users():
            if stop.is_set():
                break
            try:
                set_current_user(user['user_id'], user['username'], bool(user['is_admin']))
                prepare()
            except Exception:
                logging.getLogger(__name__).exception('Daily Brief preparation failed for %s', user['user_id'])
    finally:
        set_current_user('system', 'system', False)


def run(stop):
    while not stop.is_set():
        try:
            refresh_once(stop)
        except Exception:
            logging.getLogger(__name__).exception('Daily Brief cycle failed')
        stop.wait(60)
