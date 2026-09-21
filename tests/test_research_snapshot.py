import unittest
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

    def test_user_and_settings_isolation_and_bound(self):
        module.research_snapshot()
        with patch('auth.context.get_current_user_id', return_value='other'):
            module.research_snapshot()
        with patch('config.get_settings', return_value={'paper_trading': False}):
            module.research_snapshot()
        self.assertEqual(self.build.call_count, 3)
        self.assertEqual(len(module._cache), 2)

    def test_concurrent_build_rejected(self):
        module._build.acquire()
        try:
            with self.assertRaises(HTTPException) as ctx:
                module.research_snapshot()
            self.assertEqual(ctx.exception.status_code, 503)
            self.build.assert_not_called()
        finally:
            module._build.release()

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


if __name__ == '__main__':
    unittest.main()
