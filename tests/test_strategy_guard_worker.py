import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
from auth.context import get_current_user_id
from api import strategy_guard
import config
import strategy_health.closed_trade_guard


class StrategyGuardWorkerTests(unittest.TestCase):
    def test_scopes_each_account_and_continues_after_failure(self):
        seen = []
        def enforce():
            seen.append(get_current_user_id())
            if len(seen) == 1:
                raise ValueError('unavailable')
        users = [{'user_id': uid, 'username': uid, 'is_admin': False} for uid in ['one', 'two']]
        with patch.dict('sys.modules', {'auth.users': SimpleNamespace(list_users=lambda: users)}), \
             patch('config.get_db_path', return_value=Mock(is_file=lambda: True)), \
             patch('strategy_health.closed_trade_guard.enforce', side_effect=enforce), \
             self.assertLogs('api.strategy_guard', level='ERROR'):
            strategy_guard.refresh_once(Event())
        self.assertEqual(['one', 'two'], seen)
        self.assertEqual('system', get_current_user_id())

    def test_checks_on_startup_and_every_thirty_seconds_without_page(self):
        stop = Event()
        def wait(seconds):
            self.assertEqual(30, seconds)
            stop.set()
        with patch.object(strategy_guard, 'refresh_once') as refresh, patch.object(stop, 'wait', side_effect=wait):
            strategy_guard.run(stop)
            refresh.assert_called_once_with(stop)
