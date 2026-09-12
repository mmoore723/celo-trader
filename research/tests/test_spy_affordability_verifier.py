import copy
import unittest
from unittest.mock import patch

from research.jobs import replay_spy_affordable_contracts as producer
from research.jobs.verify_spy_affordability import validate, summarize
from research.tests import test_spy_affordable_contracts as fixtures


class IndependentVerifierTests(unittest.TestCase):
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
