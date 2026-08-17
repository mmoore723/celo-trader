import unittest

from research.jobs.tune_market_relative_snapback import period


class MarketRelativeSnapbackTuningTests(unittest.TestCase):
    def test_periods_are_chronological(self):
        from datetime import date
        self.assertEqual(period(date(2026, 5, 29)), "selection")
        self.assertEqual(period(date(2026, 6, 1)), "validation")
        self.assertEqual(period(date(2026, 7, 1)), "later")


if __name__ == "__main__":
    unittest.main()
