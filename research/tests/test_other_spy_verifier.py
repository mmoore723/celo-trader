import copy
import unittest

from research.tests import test_spy_structure_replay as fixture_module
from research.jobs.replay_two_leg_initial_loss import compare
from research.jobs.verify_other_spy_structure import verify


class OtherSpyVerifierTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.SpyStructureReplayTests()
        fixture.setUp()
        self.row = fixture.run_pair()
        self.sid = 'V2_SPY_AFTERNOON_FVG'
        self.retained = {'rows': [dict(id=self.sid+'|example', independent=True,
            control=dict(contract=fixture.entry['contract'], entry_time=fixture.entry['entry_time'],
                         entry_ask=fixture.entry['entry_ask'], exit_time=fixture.entry['exit_time'],
                         net=self.row['control']['net']), control_path=fixture.path)]}
        self.result = {'results': {self.sid: {'test': dict(rows=[self.row],
             all_activity=compare([self.row]), independent=compare([self.row]))}}}

    def test_original_prices_and_costs_reconcile(self):
        output = verify(self.result, self.retained)
        self.assertEqual(1, output[self.sid]['test']['full_original_cohort']['count'])

    def test_same_snapshot_fill_is_rejected(self):
        self.row['variant']['decision_at'] = self.row['variant']['exit_time']
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            verify(self.result, self.retained)

    def test_changed_summary_is_rejected(self):
        self.result['results'][self.sid]['test']['independent']['variant']['net'] = '999'
        with self.assertRaisesRegex(ValueError, 'Summary'):
            verify(self.result, self.retained)

    def test_duplicate_entries_are_rejected(self):
        self.result['results'][self.sid]['test']['rows'].append(copy.deepcopy(self.row))
        with self.assertRaisesRegex(ValueError, 'repeated'):
            verify(self.result, self.retained)

    def test_fabricated_missing_result_profit_is_rejected(self):
        self.row['variant'] = dict(status='missing_context', net='10')
        with self.assertRaisesRegex(ValueError, 'fabricated'):
            verify(self.result, self.retained)


if __name__ == '__main__':
    unittest.main()
