import json
import logging
from datetime import time

from fastapi import HTTPException


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
    saved = _saved()
    if saved.get('date') != _now_et().date().isoformat():
        raise HTTPException(503, 'Today\'s brief is not ready. Preparation starts at 9:00 AM ET, without opening this page.', headers={'Retry-After': '60'})
    return [{**row, 'prepared_at': saved['prepared_at']} for row in saved['rows']]


def prepare():
    from database import _now_et
    from config import get_api_keys
    from config.atomic_files import atomic_write_json
    from api.routes.market import build_premarket_report
    now = _now_et()
    if now.time() < time(9) or _saved().get('date') == now.date().isoformat():
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
