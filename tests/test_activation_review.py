import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from strategy_health.activation_review import dossier, approve
from strategy_health.pair_recommendations import assess
from tests.test_pair_recommendations import trades


class ActivationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = patch('config.get_user_data_dir', return_value=Path(self.temp.name))
        self.directory.start()
        self.addCleanup(self.directory.stop)
        self.db = patch('config.get_db_path', return_value='paper.db')
        self.db.start()
        self.addCleanup(self.db.stop)
        self.settings = {'paper_trading': True, 'active_broker_account_id': 'A'}
        self.evidence = assess(trades([20, 20, -10, 20, -10] * 4))
        self.matrix = {'strategies': [{'strategy_id': 'V2_VWAP_PULLBACK', 'version': 'research.1',
                       'display_name': 'VWAP Pullback', 'pairs': [{'ticker': 'AMZN', 'tradable': False,
                       'recommendation': self.evidence, 'quote_coverage_pct': 75, 'setups': 30}]}]}

    def review(self, settings=None):
        return dossier(self.matrix, settings or self.settings, 'V2_VWAP_PULLBACK', 'AMZN', 'research.1')

    def test_known_rules_and_gaps_are_exposed_without_grant(self):
        r = self.review()
        self.assertFalse(r['can_enable'])
        self.assertIn('EMA8', r['rules']['entry'])
        self.assertIn('75-bar', r['rules']['exit'])
        self.assertEqual(64, len(r['rules']['source_sha256']))
        self.assertEqual(75, r['coverage']['quote_coverage_pct'])
        self.assertIsNone(r['coverage']['option_result_days'])

    def test_save_is_durable_idempotent_and_never_changes_settings(self):
        r = self.review()
        with patch('config.save_settings', side_effect=AssertionError('No trading writes')):
            first = approve(r, self.settings, r['token'], 'exact', '', True, 'admin')
            second = approve(r, self.settings, r['token'], 'exact', '', True, 'admin')
        self.assertEqual(first, second)
        self.assertEqual(first, self.review()['approval'])
        self.assertFalse(first['trading_enabled_by_request'])

    def test_account_mode_version_and_ticker_are_isolated(self):
        r = self.review()
        approve(r, self.settings, r['token'], 'exact', '', True, 'admin')
        for settings in ({**self.settings, 'paper_trading': False}, {**self.settings, 'active_broker_account_id': 'B'}):
            self.assertIsNone(self.review(settings)['approval'])
        for ticker, version in [('MSFT', 'research.1'), ('AMZN', 'research.2')]:
            with self.assertRaises(ValueError):
                dossier(self.matrix, self.settings, 'V2_VWAP_PULLBACK', ticker, version)

    def test_changed_evidence_rejects_old_token(self):
        r = self.review()
        self.matrix['strategies'][0]['pairs'][0]['quote_coverage_pct'] = 76
        with self.assertRaises(ValueError):
            approve(self.review(), self.settings, r['token'], 'exact', '', True, 'admin')

    def test_answers_required_and_conflicting_decision_preserved(self):
        r = self.review()
        for choice, notes, ack in [('', '', True), ('changes', '', True), ('exact', '', False), ('exact', 'change stop', True)]:
            with self.assertRaises(ValueError):
                approve(r, self.settings, r['token'], choice, notes, ack, 'admin')
        approve(r, self.settings, r['token'], 'changes', 'Clarify contract selection', True, 'admin')
        with self.assertRaises(ValueError):
            approve(r, self.settings, r['token'], 'exact', '', True, 'admin')
        self.assertEqual('changes_requested', self.review()['approval']['status'])

    def test_routes_require_admin_and_revalidate_server_evidence(self):
        from api.routes.settings import get_activation_review, approve_activation_review, ActivationReviewPayload
        denied = SimpleNamespace(state=SimpleNamespace(is_admin=False, user_id='a'))
        with self.assertRaises(HTTPException) as exc:
            get_activation_review('V2_VWAP_PULLBACK', 'AMZN', 'research.1', denied)
        self.assertEqual(403, exc.exception.status_code)
        request = SimpleNamespace(state=SimpleNamespace(is_admin=True, user_id='a'))
        with patch('config.get_settings', return_value=self.settings), patch('api.recommendation_snapshot.for_decision', return_value=self.matrix):
            with self.assertRaises(HTTPException) as exc:
                approve_activation_review('V2_VWAP_PULLBACK', 'AMZN', ActivationReviewPayload(
                    version='research.1', token='forged', choice='exact', acknowledged=True), request)
            self.assertEqual(409, exc.exception.status_code)
