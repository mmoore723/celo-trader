import unittest
from datetime import datetime
from threading import Event
from unittest.mock import Mock, patch
from types import SimpleNamespace
from auth.context import get_current_user_id, get_current_is_admin
from api import research_refresh
import config
import database
import api.research_snapshot
import strategy_health.research_matrix


class ResearchRefreshTests(unittest.TestCase):
    def test_prepares_recommendations_without_opening_settings(self):
        from api import recommendation_snapshot
        users = [{'user_id': 'one', 'username': 'one', 'is_admin': False}]
        settings = {'paper_trading': True}
        with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: users)}), \
             patch('config.get_db_path', return_value=Mock(is_file=lambda: True)), \
             patch('config.get_settings', return_value=settings), \
             patch('api.research_snapshot.research_snapshot', return_value={'strategies': []}), \
             patch.object(recommendation_snapshot, 'remember') as remember:
            research_refresh.refresh_once(Event())
            remember.assert_called_once_with({'strategies': []}, settings)

    def test_first_page_request_reuses_automatically_prepared_snapshot(self):
        from pathlib import Path
        from api import research_snapshot as snapshots
        from auth.context import set_current_user
        snapshots._cache.clear()
        users = [{'user_id': uid, 'username': uid, 'is_admin': False} for uid in ['one', 'two', 'three']]
        try:
            with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: users)}), \
                 patch('config.get_db_path', return_value=Path('/test/paper.db')), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch('config.get_settings', return_value={'paper_trading': True}), \
                 patch('database._now_et', return_value=datetime(2026, 9, 24)), \
                 patch('strategy_health.research_matrix.build_research_matrix', return_value={'strategies': []}) as build:
                research_refresh.refresh_once(Event())
                set_current_user('one', 'one', False)
                result = snapshots.research_snapshot(90, start_date='2026-06-27', end_date='2026-09-24', allow_stale=True)
                self.assertEqual(result['strategies'], [])
                self.assertFalse(result['snapshot']['refreshing'])
                self.assertEqual(build.call_count, 3)
                build.assert_called_with(90, start_date='2026-06-27', end_date='2026-09-24')
        finally:
            snapshots._cache.clear()
            set_current_user('system', 'system', False)

    def test_prepares_default_window_without_a_page_request_and_isolates_users(self):
        users = [{'user_id': 'one', 'username': 'one', 'is_admin': True},
                 {'user_id': 'two', 'username': 'two', 'is_admin': False}]
        contexts = []
        def build(*args, **kwargs):
            contexts.append((get_current_user_id(), get_current_is_admin()))
        with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: users)}), \
             patch('config.get_db_path', return_value=Mock(is_file=lambda: True)), \
             patch('database._now_et', return_value=datetime(2026, 9, 24)), \
             patch('api.research_snapshot.research_snapshot', side_effect=build) as snapshot:
            research_refresh.refresh_once(Event())
        self.assertEqual(contexts, [('one', True), ('two', False)])
        snapshot.assert_called_with(90, start_date='2026-06-27', end_date='2026-09-24')
        self.assertEqual(get_current_user_id(), 'system')
        self.assertFalse(get_current_is_admin())

    def test_one_failure_does_not_prevent_next_user_refresh(self):
        users = [{'user_id': uid, 'username': uid, 'is_admin': False} for uid in ['one', 'two']]
        with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: users)}), \
             patch('config.get_db_path', return_value=Mock(is_file=lambda: True)), \
             patch('api.research_snapshot.research_snapshot', side_effect=[ValueError('unavailable'), {}]) as snapshot, \
             self.assertLogs('api.research_refresh', level='ERROR'):
            research_refresh.refresh_once(Event())
        self.assertEqual(snapshot.call_count, 2)
        self.assertEqual(get_current_user_id(), 'system')

    def test_does_not_create_databases_for_unused_accounts(self):
        with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: [{'user_id': 'one', 'username': 'one', 'is_admin': False}])}), \
             patch('config.get_db_path', return_value=Mock(is_file=lambda: False)), \
             patch('api.research_snapshot.research_snapshot') as snapshot:
            research_refresh.refresh_once(Event())
        snapshot.assert_not_called()

    def test_worker_runs_on_boot_then_waits_and_stops(self):
        stop = Event()
        def wait(seconds):
            self.assertEqual(seconds, 120)
            stop.set()
        with patch.object(stop, 'wait', side_effect=wait), \
             patch.object(research_refresh, 'refresh_once') as refresh:
            research_refresh.run(stop)
        refresh.assert_called_once_with(stop)
