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
                from strategy_health.premium_research import BACKGROUND_ANALYSIS, ANALYSIS_DEADLINE, ANALYSIS_KEYS, SEEN_KEYS
                from time import monotonic
                token=BACKGROUND_ANALYSIS.set(True)
                budget=ANALYSIS_DEADLINE.set(monotonic()+20)
                keys=ANALYSIS_KEYS.set(None)
                seen=set(); seen_token=SEEN_KEYS.set(seen)
                try:
                    matrix = research_snapshot(90, start_date=(today - timedelta(days=89)).isoformat(),
                                               end_date=today.isoformat(), force_refresh=True)
                finally:
                    ANALYSIS_KEYS.reset(keys)
                    SEEN_KEYS.reset(seen_token)
                    ANALYSIS_DEADLINE.reset(budget)
                    BACKGROUND_ANALYSIS.reset(token)
                if matrix and 'strategies' in matrix:
                    remember(matrix, get_settings())
                    if seen:
                        # Retire obsolete work requests, never evidence or reports.
                        from database import get_conn
                        settings=get_settings()
                        with get_conn() as conn:
                            queued=conn.execute('SELECT bucket FROM premium_exit_work WHERE account IS ? AND mode=?',
                                (settings.get('active_broker_account_id'),'paper' if settings.get('paper_trading',True) else 'live')).fetchall()
                            conn.executemany('DELETE FROM premium_exit_work WHERE bucket=?',[(r[0],) for r in queued if r[0] not in seen])
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
