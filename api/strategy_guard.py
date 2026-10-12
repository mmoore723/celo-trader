import logging


def refresh_once(stop):
    from auth.context import set_current_user
    from auth.users import list_users
    from config import get_db_path
    from strategy_health.closed_trade_guard import enforce
    try:
        for user in list_users():
            if stop.is_set():
                break
            try:
                set_current_user(user['user_id'], user['username'], bool(user['is_admin']))
                if get_db_path().is_file():
                    enforce()
            except Exception:
                logging.getLogger(__name__).exception('Closed-trade PF check failed for %s', user['user_id'])
    finally:
        set_current_user('system', 'system', False)


def run(stop):
    while not stop.is_set():
        try:
            refresh_once(stop)
        except Exception:
            logging.getLogger(__name__).exception('Closed-trade PF cycle failed')
        stop.wait(30)
