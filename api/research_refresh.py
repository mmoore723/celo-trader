from datetime import timedelta
import logging

REFRESH_SECONDS = 120


def refresh_once(stop):
    from auth.context import set_current_user
    from auth.users import list_users
    from config import get_db_path
    from database import _now_et
    from api.research_snapshot import research_snapshot
    from api.recommendation_snapshot import remember
    from config import get_settings

    try:
        for user in list_users():
            if stop.is_set():
                break
            try:
                set_current_user(user['user_id'], user['username'], bool(user['is_admin']))
                if not get_db_path().is_file():
                    continue
                today = _now_et().date()
                matrix = research_snapshot(90, start_date=(today - timedelta(days=89)).isoformat(),
                                           end_date=today.isoformat())
                if matrix and 'strategies' in matrix:
                    remember(matrix, get_settings())
            except Exception:
                logging.getLogger(__name__).exception('Research refresh failed for user %s', user['user_id'])
    finally:
        set_current_user('system', 'system', False)


def run(stop):
    while not stop.is_set():
        try:
            refresh_once(stop)
        except Exception:
            logging.getLogger(__name__).exception('Research refresh cycle failed')
        stop.wait(REFRESH_SECONDS)
