import unittest

from research.tests import test_context_fallback as fixtures
from research.jobs.replay_context_fallback import complete_pair
from research.jobs.verify_context_fallback import check_pair


class FallbackVerifierTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ContextFallbackTests()
        fixture.setUp()
        self.original, self.path = fixture.original, fixture.path
        self.result = complete_pair(self.original, self.path)

    def test_valid_fallback_reconciles(self):
        check_pair(self.result, self.original, self.path)

    def test_missing_context_cannot_disable_guard(self):
        self.path[5]['bid'] = '4'
        with self.assertRaisesRegex(ValueError, 'guard/timer'):
            check_pair(self.result, self.original, self.path)

    def test_old_control_cannot_be_replaced(self):
        self.result['control']['net'] = '1000'
        with self.assertRaisesRegex(ValueError, 'Original evidence'):
            check_pair(self.result, self.original, self.path)

    def test_trigger_quote_is_not_a_fill(self):
        self.result['variant']['exit_time'] = self.result['variant']['decision_at']
        with self.assertRaisesRegex(ValueError, 'later executable'):
            check_pair(self.result, self.original, self.path)

    def test_costs_are_recalculated_independently(self):
        self.result['variant']['net'] = '2000'
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            check_pair(self.result, self.original, self.path)


if __name__ == '__main__':
    unittest.main()
