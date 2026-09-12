import copy
import unittest
from unittest.mock import patch

from research.jobs import replay_spy_affordable_contracts as producer
from research.jobs.verify_spy_affordability import validate, summarize, verify_ticker_routing
from research.tests.test_account_controls_replay import trade, SETTINGS
from research.jobs.replay_account_controls import replay
from research.tests import test_spy_affordable_contracts as fixtures


class IndependentVerifierTests(unittest.TestCase):
    def routing_fixture(self):
        rows = [{**trade(1, end='10:30', exit=1.1), 'ticker': 'SPY'},
                {**trade(2, start='10:31'), 'ticker': 'SPY'}]
        for row in rows:
            for key in ('entry_time', 'exit_time'):
                row[key] += '-04:00'
        return rows, replay(rows, [], SETTINGS, corrected=False, ticker_routing=True)

    def test_independent_routing_accepts_correct_cooldown(self):
        rows, result = self.routing_fixture()
        verify_ticker_routing(rows, result)

    def test_independent_routing_rejects_accepted_cooldown_entry(self):
        rows, result = self.routing_fixture()
        result['decisions'][1] = {'id': 2, 'action': 'enter'}
        with self.assertRaisesRegex(ValueError, 'violates ticker routing'):
            verify_ticker_routing(rows, result)

    def test_independent_routing_rejects_missing_decision(self):
        rows, result = self.routing_fixture()
        result['decisions'].pop()
        with self.assertRaisesRegex(ValueError, 'cohort'):
            verify_ticker_routing(rows, result)

    def test_independent_routing_rejects_false_ticker_block(self):
        rows, result = self.routing_fixture()
        result['decisions'][1]['reason'] = 'ticker_already_open'
        with self.assertRaisesRegex(ValueError, 'Incorrect ticker routing'):
            verify_ticker_routing(rows, result)

    def setUp(self):
        fixture = fixtures.AffordableProfileTests()
        fixture.setUp()
        self.original = fixture.entry
        self.original['id'] = self.original['strategy_id'] + '|test'
        self.original['date'] = '2026-05-12'
        with patch.object(producer, 'snapshots', return_value=fixture.groups()):
            self.row = producer.day_replay([self.original], None)[0]
        self.data = dict(complete=True, protocol=producer.PROTOCOL, rows=[self.row])

    def test_valid_source_and_candidate_pass(self):
        validate(self.data, {self.row['id']: self.original})

    def test_tampered_profit_is_rejected(self):
        self.row['candidate']['net'] = '600'
        with self.assertRaisesRegex(ValueError, 'P&L'):
            validate(self.data, {self.row['id']: self.original})

    def test_changed_strategy_identity_is_rejected(self):
        self.row['strategy_id'] = 'V2_SPY_AFTERNOON_FVG'
        with self.assertRaisesRegex(ValueError, 'identity'):
            validate(self.data, {self.row['id']: self.original})

    def test_missing_endpoint_is_not_validated(self):
        self.row['candidate_path'].pop()
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            validate(self.data, {self.row['id']: self.original})

    def test_control_cohort_cannot_shrink(self):
        with self.assertRaisesRegex(ValueError, 'cohort'):
            validate(self.data, {self.row['id']: self.original, 'missing': self.original})

    def test_missing_candidate_remains_visible_in_summary(self):
        missing = copy.deepcopy(self.row)
        missing['id'] += 'missing'
        missing['candidate'] = {'status': 'no_affordable_contract'}
        result = summarize([self.row, missing])[self.row['strategy_id']]['all']
        self.assertEqual(2, result['control']['count'])
        self.assertEqual(1, result['candidate']['count'])
        self.assertEqual(1, result['candidate_status']['no_affordable_contract'])


if __name__ == '__main__':
    unittest.main()
