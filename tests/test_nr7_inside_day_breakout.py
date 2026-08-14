from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar
from research.engine.strategies.nr7_inside_day_breakout import NR7InsideDayBreakout


class NR7InsideDayBreakoutTests(unittest.TestCase):
    def test_no_signal_without_prior_sessions(self):
        strategy = NR7InsideDayBreakout()
        bar = Bar(datetime(2026, 1, 5, 10), 100, 101, 99, 100.5, 1000)
        self.assertIsNone(strategy.evaluate([bar]))

    def test_session_grouping_is_chronological(self):
        start = datetime(2026, 1, 5, 9, 30)
        bars = [Bar(start + timedelta(days=day), 100, 101, 99, 100, 1000) for day in range(3)]
        self.assertEqual([1, 1, 1], [len(group) for group in NR7InsideDayBreakout._sessions(bars)])


if __name__ == "__main__":
    unittest.main()
