import unittest
from unittest.mock import patch

from fastapi import HTTPException
from api import recommendation_snapshot as snapshot
from api.routes.settings import get_strategy_recommendations, set_strategy_recommendation_consent, StrategyConsentPayload
from tests.test_trend_research_execution import matrix, SID, RULE


class RecommendationSnapshotTests(unittest.TestCase):
    def test_move_to_research_only_does_not_require_unexpired_research_offer(self):
        with patch('config.get_settings', return_value={'paper_trading': True}), \
             patch('config.get_user_data_dir', return_value=__import__('pathlib').Path('/tmp/celo-test-user')), \
             patch('config.save_settings') as save, \
             patch('api.recommendation_snapshot.for_decision', side_effect=AssertionError('No offer needed to stop entries')):
            self.assertEqual({'ok': True}, set_strategy_recommendation_consent(
                SID, 'SPY', StrategyConsentPayload(decision='research_only', fingerprint='expired')))
            self.assertEqual({'strategy_pair_pauses': {f'shared:{SID}:SPY': True}}, save.call_args.args[0])
            with self.assertRaises(HTTPException):
                set_strategy_recommendation_consent('UNKNOWN', 'SPY', StrategyConsentPayload(decision='research_only'))

    def setUp(self):
        snapshot._offers.clear()

    def test_click_uses_server_evidence_without_aggregate_rebuild_or_balance_dependency(self):
        data, evidence = matrix()
        settings = {'paper_trading': True, 'risk_per_trade': .38, 'last_known_balance': 4000}
        with patch('config.get_settings', return_value=settings), patch('config.save_settings') as save, \
             patch('api.research_snapshot.research_snapshot', return_value=data) as aggregate:
            get_strategy_recommendations()
            aggregate.side_effect = AssertionError('Approval must not rebuild research')
            settings['last_known_balance'] = 4001
            self.assertEqual({'ok': True}, set_strategy_recommendation_consent(
                SID, 'SPY', StrategyConsentPayload(decision='enable', fingerprint=evidence['fingerprint'])))
        self.assertTrue(save.call_args.args[0][RULE.setting_key])
        self.assertNotIn('risk_per_trade', save.call_args.args[0])
        self.assertEqual(1, aggregate.call_count)

    def test_expiration_user_database_and_account_mode_are_isolated(self):
        data, _ = matrix()
        with patch('auth.context.get_current_user_id', return_value='a') as user, \
             patch('config.get_db_path', return_value='one.db') as db, \
             patch.object(snapshot, 'monotonic', return_value=10) as clock:
            snapshot.remember(data, {'paper_trading': True, 'active_broker_account_id': 'one'})
            base = {'paper_trading': True, 'active_broker_account_id': 'one'}
            self.assertEqual(data, snapshot.for_decision(base))
            for settings in ({**base, 'paper_trading': False}, {**base, 'active_broker_account_id': 'two'}):
                with self.assertRaises(HTTPException):
                    snapshot.for_decision(settings)
            user.return_value = 'b'
            with self.assertRaises(HTTPException):
                snapshot.for_decision(base)
            user.return_value = 'a'
            db.return_value = 'two.db'
            with self.assertRaises(HTTPException):
                snapshot.for_decision(base)
            db.return_value = 'one.db'
            clock.return_value = 311
            with self.assertRaises(HTTPException):
                snapshot.for_decision(base)

    def test_forged_fingerprint_and_changed_integrity_cannot_save(self):
        data, evidence = matrix()
        settings = {'paper_trading': True}
        with patch('config.get_settings', return_value=settings), patch('config.save_settings') as save, \
             patch('api.research_snapshot.research_snapshot', return_value=data):
            get_strategy_recommendations()
            with self.assertRaises(HTTPException):
                set_strategy_recommendation_consent(SID, 'SPY', StrategyConsentPayload(decision='enable', fingerprint='forged'))
            with patch('config.strategy_catalog.reviewed_strategy_integrity_errors', return_value={SID: ['changed']}):
                with self.assertRaises(HTTPException):
                    set_strategy_recommendation_consent(SID, 'SPY', StrategyConsentPayload(decision='enable', fingerprint=evidence['fingerprint']))
        save.assert_not_called()
