import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config.strategy_retirement import identity, is_retired, updates, active_ids, inventory
from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids, enabled_observation_strategy_ids, public_strategy_catalog
from trading.tested_strategy_research import enabled_tested_research_ids, public_tested_research_strategies


class StrategyRetirementTests(unittest.TestCase):
    def test_exact_version_and_source_alias(self):
        settings = updates({}, 'RESEARCH_FAILED_RANGE_V2', '2.1.0.research.2', True)
        self.assertTrue(is_retired(settings, 'V2_FAILED_OR_BREAK_VWAP_REVERSION', '2.1.0.research.2'))
        self.assertFalse(is_retired(settings, 'V2_FAILED_OR_BREAK_VWAP_REVERSION', '2.1.0'))
        self.assertNotIn('RESEARCH_FAILED_RANGE_V2', active_ids(settings, set(REVIEWED_STRATEGIES)))
        self.assertIn('V2_FAILED_OR_BREAK_VWAP_REVERSION', active_ids(settings, set(REVIEWED_STRATEGIES)))

    def test_trend_removed_from_both_modes_and_new_research_only(self):
        sid = 'V2_TREND_CONT'
        original = {REVIEWED_STRATEGIES[sid].setting_key: True}
        removed = {**original, **updates(original, sid, 'research.1', True)}
        for paper in (True, False):
            self.assertNotIn(sid, enabled_reviewed_strategy_ids(removed, paper=paper))
        self.assertNotIn(sid, enabled_tested_research_ids(removed))
        self.assertIn(sid, enabled_tested_research_ids(removed, include_removed=True))
        self.assertNotIn(sid, active_ids(removed, set(REVIEWED_STRATEGIES)))
        self.assertIn(sid, REVIEWED_STRATEGIES)
        self.assertIn(sid, enabled_tested_research_ids(original))
        self.assertEqual(original, {REVIEWED_STRATEGIES[sid].setting_key: True})
        row = next(row for row in public_strategy_catalog(removed) if row['strategy_id'] == sid)
        self.assertTrue(row['removed'])
        self.assertEqual(row['trading_tickers'], [])

    def test_restore_does_not_grant_authority_or_change_other_settings(self):
        settings = {'paper_trading': True, 'risk_pct': 38, 'research_strategy_ids': []}
        removed = {**settings, **updates(settings, 'V2_TREND_CONT', 'research.1', True)}
        restored = {**removed, **updates(removed, 'V2_TREND_CONT', 'research.1', False)}
        self.assertEqual(restored, {**settings, 'retired_strategy_versions': []})
        self.assertNotIn('V2_TREND_CONT', enabled_tested_research_ids(restored))
        self.assertNotIn('V2_TREND_CONT', enabled_reviewed_strategy_ids(restored))

    def test_observation_only_and_library_only(self):
        rule = next(rule for rule in REVIEWED_STRATEGIES.values() if rule.observation_only)
        settings = {rule.setting_key: True, **updates({}, rule.strategy_id, rule.version, True)}
        self.assertNotIn(rule.strategy_id, enabled_observation_strategy_ids(settings))
        settings = updates({}, 'V2_EMA_PULLBACK_RTH', 'research.3', True)
        row = next(row for row in public_tested_research_strategies(settings) if row['strategy_id'] == 'V2_EMA_PULLBACK_RTH')
        self.assertTrue(row['removed'])
        self.assertFalse(row['enabled'])

    def test_unknown_rejected_inventory_deduplicated(self):
        with self.assertRaises(ValueError):
            updates({}, 'V2_TREND_CONT', 'wrong-version', True)
        rows = inventory({})
        self.assertEqual(len(rows), len({identity(row['strategy_id'], row['version']) for row in rows}))

    def test_endpoint_persists_only_retirement_and_stops_stale_worker(self):
        from api.routes.settings import set_strategy_removal, StrategyRemovalPayload
        from pathlib import Path
        with patch('config.get_settings', return_value={'risk_pct': 38}), \
             patch('config.get_user_data_dir', return_value=Path('/tmp/celo-retirement-test')), \
             patch('config.save_settings') as save, \
             patch('auth.context.get_current_user_id', return_value='test-user'), \
             patch('trading.loop.research_worker.stop_research') as stop:
            result = set_strategy_removal(StrategyRemovalPayload(strategy_id='V2_TREND_CONT', version='research.1', removed=True), SimpleNamespace(state=SimpleNamespace(is_admin=True)))
        self.assertEqual(result, {'ok': True})
        save.assert_called_once_with({'retired_strategy_versions': ['V2_TREND_CONT:research.1']})
        stop.assert_called_once_with('test-user')

    def test_archive_and_restore_are_admin_only(self):
        from api.routes.settings import get_strategy_removals, set_strategy_removal, StrategyRemovalPayload
        from fastapi import HTTPException
        settings = updates({}, 'V2_TREND_CONT', 'research.1', True)
        for admin in (False, True):
            request = SimpleNamespace(state=SimpleNamespace(is_admin=admin))
            with patch('config.get_settings', return_value=settings), \
                 patch('trading.state.get_user_state', return_value={'scan_watchlist': ['SPY', 'QQQ']}):
                result = get_strategy_removals(request)
            self.assertEqual(result['can_restore'], admin)
            self.assertEqual(len(result['strategies']), 1 if admin else 0)
        with self.assertRaises(HTTPException) as caught, patch('config.save_settings') as save:
            set_strategy_removal(StrategyRemovalPayload(strategy_id='V2_TREND_CONT', version='research.1', removed=False), SimpleNamespace(state=SimpleNamespace(is_admin=False)))
        self.assertEqual(caught.exception.status_code, 403)
        save.assert_not_called()

    def test_retired_hidden_from_research_without_mutating_cached_history(self):
        from api.routes.strategy_health import _research_snapshot
        original = {'strategies': [
            {'strategy_id': 'V2_TREND_CONT', 'version': 'research.1'},
            {'strategy_id': 'V2_SPY_TREND_CONT', 'version': '2.1.0'}]}
        with patch('api.research_snapshot.research_snapshot', return_value=original), \
             patch('config.get_settings', return_value=updates({}, 'V2_TREND_CONT', 'research.1', True)):
            result = _research_snapshot(90, None, None)
        self.assertEqual(result['strategies'], [original['strategies'][1]])
        self.assertEqual(len(original['strategies']), 2)

    def test_retired_position_keeps_session_exit(self):
        from datetime import datetime, timedelta
        from trading.position_manager.manage import _evaluate_reviewed_strategy_exit
        close = datetime.fromisoformat('2026-10-14T16:00:00-04:00')
        with patch('config.get_settings', return_value=updates({}, 'V2_TREND_CONT', 'research.1', True)):
            result = _evaluate_reviewed_strategy_exit({'strategy_id': 'V2_TREND_CONT'}, close.replace(hour=10), close-timedelta(minutes=5), one_minute_bars=None, five_minute_bars=None, session_close=close)
        self.assertEqual(result, (True, 'research_session_close'))


if __name__ == '__main__':
    unittest.main()
