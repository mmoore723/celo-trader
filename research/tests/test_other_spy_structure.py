import unittest
from research.jobs.replay_other_spy_structure import adapt_entry, source_entries


class OtherSpyStructureTests(unittest.TestCase):
    def setUp(self):
        self.sid = 'V2_FAILED_OR_BREAK_VWAP_REVERSION'
        self.row = dict(candidate_id='test', profile='reviewed_bounds', status='priced',
                        native=True, native_independent=True, independent=True, stop=100)

    def test_failed_range_uses_original_stop_without_mutating_source(self):
        result = adapt_entry(self.sid, self.row)
        self.assertEqual({'v2_stop': 100}, result['signal_meta'])
        self.assertNotIn('signal_meta', self.row)

    def test_fvg_keeps_original_stop_and_other_metadata(self):
        row = {**self.row, 'signal_meta': {'v2_stop': 99, 'gap_lower': 100}}
        result = adapt_entry('V2_SPY_AFTERNOON_FVG', row)
        self.assertEqual(row['signal_meta'], result['signal_meta'])
        self.assertIsNot(row['signal_meta'], result['signal_meta'])

    def test_non_native_and_other_profiles_rejected(self):
        for override in [{'native': False}, {'profile': 'research_primary'}, {'native_independent': False}]:
            with self.assertRaises(ValueError):
                adapt_entry(self.sid, {**self.row, **override})

    def test_missing_original_stop_rejected(self):
        with self.assertRaisesRegex(ValueError, 'thesis stop'):
            adapt_entry('V2_SPY_AFTERNOON_FVG', {**self.row, 'signal_meta': {}})

    def test_uses_control_paths_not_affordable_paths(self):
        retained = {'rows': [dict(id=self.sid+'|test', strategy_id=self.sid, independent=True,
                                  control_path=['original'], candidate_path=['cheaper'])]}
        pairs = source_entries(self.sid, {'rows': [self.row]}, retained)
        self.assertEqual(['original'], pairs[0][1]['snapshots'])

    def test_missing_path_blocks_comparison(self):
        with self.assertRaisesRegex(ValueError, 'cohort'):
            source_entries(self.sid, {'rows': [self.row]}, {'rows': []})


if __name__ == '__main__':
    unittest.main()
