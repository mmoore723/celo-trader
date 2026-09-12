import copy
from datetime import timedelta
import unittest

from research.jobs.replay_context_fallback import complete_pair
from research.tests import test_spy_structure_replay as fixtures


class ContextFallbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SpyStructureReplayTests()
        self.fixture.setUp()
        self.fixture.market.at.side_effect = ValueError('Missing completed candle')
        self.original = self.fixture.run_pair()
        self.path = self.fixture.path

    def test_unavailable_context_preserves_timer_without_inventing_indicators(self):
        result = complete_pair(self.original, self.path)
        self.assertEqual(self.original['control']['net'], result['variant']['net'])
        self.assertEqual('original_time_cap', result['variant']['reason'])
        self.assertTrue(result['context_fallback_used'])
        self.assertEqual('missing_context', self.original['variant']['status'])
        self.assertEqual('missing_context', result['prior_variant']['status'])
        self.assertNotIn('frames', result['fallback_trace'][0])

    def test_guard_executes_on_first_missing_candle_without_context(self):
        self.path[1]['bid'] = '4'
        self.path[2]['bid'] = '3.9'
        result = complete_pair(self.original, self.path)
        self.assertEqual('maximum_premium_loss_20pct', result['variant']['reason'])
        self.assertEqual('3.9', result['variant']['bid'])
        self.assertEqual('-113.30', result['variant']['net'])

    def test_guard_remains_active_later_in_fallback(self):
        self.path[20]['bid'] = '4'
        self.path[21]['bid'] = '3.8'
        result = complete_pair(self.original, self.path)
        self.assertEqual(self.path[20]['time'], result['variant']['decision_at'])
        self.assertEqual(self.path[21]['time'], result['variant']['exit_time'])

    def test_missing_next_quote_does_not_fill_at_trigger(self):
        self.path[1]['bid'] = '4'
        del self.path[2]
        self.assertEqual('missing_quote', complete_pair(self.original, self.path)['variant']['status'])

    def test_quote_gap_is_not_converted_to_a_hold(self):
        del self.path[2:5]
        self.assertEqual('missing_path', complete_pair(self.original, self.path)['variant']['status'])

    def test_successful_structural_exit_is_unchanged(self):
        original = copy.deepcopy(self.original)
        original['variant'] = dict(original['control'])
        result = complete_pair(original, self.path)
        self.assertEqual(original['variant'], result['variant'])
        self.assertFalse(result['context_fallback_used'])

    def test_original_control_cannot_change(self):
        self.original['control']['net'] = '999'
        with self.assertRaisesRegex(ValueError, 'cost arithmetic'):
            complete_pair(self.original, self.path)

    def test_ninety_minute_timer_is_not_shortened_to_thirty(self):
        start = self.fixture.start
        self.path = [dict(self.path[0], time=(start+timedelta(minutes=i)).isoformat(),
                          bid='5.5' if i==91 else '5', ask='5.5') for i in range(92)]
        self.path[0]['ask'] = '5'
        self.original['control'].update(decision_at=(start+timedelta(minutes=90)).isoformat(),
                                        exit_time=(start+timedelta(minutes=91)).isoformat())
        result = complete_pair(self.original, self.path)
        self.assertEqual(self.original['control']['exit_time'], result['variant']['exit_time'])


if __name__ == '__main__':
    unittest.main()
