import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from fastapi import HTTPException
from api import research_snapshot as module


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        module._cache.clear()
        self.stack = []
        for name, value in [('auth.context.get_current_user_id', 'admin'),
                            ('config.get_db_path', '/test/paper.db'),
                            ('config.get_settings', {'paper_trading': True})]:
            p = patch(name, return_value=value)
            self.stack.append(p)
            p.start()
        self.builder = patch('strategy_health.research_matrix.build_research_matrix', return_value={'strategies': []})
        self.build = self.builder.start()

    def tearDown(self):
        self.builder.stop()
        for p in self.stack:
            p.stop()
        module._cache.clear()

    def test_reuses_identical_snapshot(self):
        self.assertIs(module.research_snapshot(), module.research_snapshot())
        self.build.assert_called_once_with(90)

    def test_balance_updates_do_not_rebuild_or_mutate_settings(self):
        settings = {'paper_trading': True, 'last_known_balance': 3500}
        with patch('config.get_settings', return_value=settings):
            first = module.research_snapshot()
            settings['last_known_balance'] = 3510
            self.assertIs(module.research_snapshot(), first)
        self.assertEqual(settings['last_known_balance'], 3510)
        self.build.assert_called_once_with(90)

    def test_account_and_approval_changes_still_rebuild(self):
        settings = {'paper_trading': True, 'active_broker_account_id': 'one'}
        with patch('config.get_settings', return_value=settings):
            module.research_snapshot()
            settings['active_broker_account_id'] = 'two'
            module.research_snapshot()
            settings['strategy_pair_approvals'] = {'SPY': {'user_approved': True}}
            module.research_snapshot()
        self.assertEqual(self.build.call_count, 3)

    def test_user_and_settings_isolation_and_bound(self):
        module.research_snapshot()
        with patch('auth.context.get_current_user_id', return_value='other'):
            module.research_snapshot()
        with patch('config.get_settings', return_value={'paper_trading': False}):
            module.research_snapshot()
        self.assertEqual(self.build.call_count, 3)
        self.assertEqual(len(module._cache), 3)
        for index in range(module.MAX_SNAPSHOTS):
            with patch('auth.context.get_current_user_id', return_value=f'user-{index}'):
                module.research_snapshot()
        self.assertEqual(len(module._cache), module.MAX_SNAPSHOTS)

    def test_stuck_build_wait_is_bounded(self):
        module._build.acquire()
        try:
            with patch.object(module, 'BUILD_WAIT_SECONDS', .01):
                with self.assertRaises(HTTPException) as ctx:
                    module.research_snapshot()
            self.assertEqual(ctx.exception.status_code, 503)
            self.build.assert_not_called()
        finally:
            module._build.release()

    def test_concurrent_cold_requests_share_one_build(self):
        started, finish = Event(), Event()
        def build(days):
            started.set()
            self.assertTrue(finish.wait(2))
            return {'strategies': [1]}
        self.build.side_effect = build
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(module.research_snapshot)
            self.assertTrue(started.wait(2))
            second = pool.submit(module.research_snapshot)
            third = pool.submit(module.research_snapshot)
            finish.set()
            result = first.result(timeout=2)
            self.assertIs(second.result(timeout=2), result)
            self.assertIs(third.result(timeout=2), result)
        self.build.assert_called_once_with(90)

    def test_failure_releases_build_lock(self):
        self.build.side_effect = ValueError('failure')
        with self.assertRaises(ValueError):
            module.research_snapshot()
        self.assertFalse(module._build.locked())
        self.assertFalse(module._cache)

    def test_expiration_rebuilds(self):
        with patch.object(module, 'monotonic', return_value=100):
            module.research_snapshot()
        with patch.object(module, 'monotonic', return_value=161):
            module.research_snapshot()
        self.assertEqual(self.build.call_count, 2)

    def test_date_filters_have_separate_cache_keys(self):
        module.research_snapshot(start_date='2026-09-14', end_date='2026-09-18')
        module.research_snapshot(start_date='2026-09-14', end_date='2026-09-18')
        self.build.assert_called_once_with(90, start_date='2026-09-14', end_date='2026-09-18')
        module.research_snapshot(start_date='2026-09-15', end_date='2026-09-18')
        self.assertEqual(self.build.call_count, 2)

    def test_display_returns_stale_without_waiting_and_keeps_request_context(self):
        from auth.context import _user_id_var
        module.research_snapshot()
        key = next(iter(module._cache))
        entry = module._cache[key]
        module._cache[key] = (module.monotonic() - 61, entry[1], entry[2])
        started, finish = Event(), Event()
        users = []
        def build(days):
            users.append(_user_id_var.get())
            started.set()
            self.assertTrue(finish.wait(2))
            return {'strategies': [1]}
        self.build.side_effect = build
        token = _user_id_var.set('captured-user')
        try:
            result = module.research_snapshot(allow_stale=True)
            self.assertTrue(started.wait(2))
            self.assertTrue(result['snapshot']['refreshing'])
            self.assertEqual(result['strategies'], [])
            self.assertEqual(module.research_snapshot(allow_stale=True)['strategies'], [])
            self.assertEqual(self.build.call_count, 2)
            self.assertEqual(users, ['captured-user'])
        finally:
            finish.set()
            _user_id_var.reset(token)
            self.assertTrue(module._build.acquire(timeout=2))
            module._build.release()
        result = module.research_snapshot(allow_stale=True)
        self.assertFalse(result['snapshot']['refreshing'])
        self.assertEqual(result['strategies'], [1])

    def test_display_staleness_is_bounded(self):
        module.research_snapshot()
        key = next(iter(module._cache))
        entry = module._cache[key]
        module._cache[key] = (module.monotonic() - 301, entry[1], entry[2])
        self.build.return_value = {'strategies': [2]}
        result = module.research_snapshot(allow_stale=True)
        self.assertEqual(result['strategies'], [2])
        self.assertFalse(result['snapshot']['refreshing'])

    def test_strict_caller_never_receives_stale_display_snapshot(self):
        module.research_snapshot(allow_stale=True)
        key = next(iter(module._cache))
        entry = module._cache[key]
        module._cache[key] = (module.monotonic() - 61, entry[1], entry[2])
        self.build.return_value = {'strategies': [3]}
        self.assertEqual(module.research_snapshot(), {'strategies': [3]})

    def test_display_does_not_serve_another_user_snapshot(self):
        module.research_snapshot(allow_stale=True)
        self.build.return_value = {'strategies': ['other']}
        with patch('auth.context.get_current_user_id', return_value='other'):
            result = module.research_snapshot(allow_stale=True)
        self.assertEqual(result['strategies'], ['other'])
        self.assertEqual(self.build.call_count, 2)


if __name__ == '__main__':
    unittest.main()
