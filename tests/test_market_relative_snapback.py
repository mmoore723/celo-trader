import unittest

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from research.jobs.screen_market_relative_snapback import (
    _beta,
    observations,
    qualifies,
    summarize,
)


class MarketRelativeSnapbackTests(unittest.TestCase):
    def test_beta_estimate(self):
        self.assertAlmostEqual(_beta([1, 2, 3, 4], [2, 4, 6, 8]), 2.0)

    def test_summary_uses_median_and_profit_factor(self):
        row = summarize([1.0, 0.5, -0.25])
        self.assertEqual(row["trades"], 3)
        self.assertEqual(row["median_return_pct"], 0.5)
        self.assertEqual(row["profit_factor"], 6.0)

    def test_qualification_requires_sample_and_distribution(self):
        self.assertTrue(qualifies(summarize([1.0, 0.8, 0.5, -0.2]), 4))
        self.assertFalse(qualifies(summarize([5.0, -1.0, -1.0, -1.0]), 4))
        self.assertFalse(qualifies(summarize([1.0, 0.8, -0.2]), 4))

    def test_follow_residual_flips_only_direction_not_signal(self):
        start = datetime(2026, 7, 6, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        spy, stock = [], []
        spy_price = stock_price = 100.0
        for index in range(150):
            stamp = start + timedelta(minutes=index)
            spy_open = spy_price
            stock_open = stock_price
            spy_price *= 1.0001 if index % 2 else 0.9999
            stock_price *= 1.0002 if index % 2 else 0.9998
            if index >= 80:
                stock_price *= 1.001
            spy.append(SimpleNamespace(timestamp=stamp, open=spy_open, close=spy_price))
            stock.append(SimpleNamespace(timestamp=stamp, open=stock_open, close=stock_price))

        faded = observations(
            spy, stock, lookback_minutes=60, shock_minutes=15,
            z_threshold=1.0, hold_minutes=5,
        )
        followed = observations(
            spy, stock, lookback_minutes=60, shock_minutes=15,
            z_threshold=1.0, hold_minutes=5, follow_residual=True,
        )
        self.assertTrue(faded)
        self.assertEqual(faded[0]["signal_time"], followed[0]["signal_time"])
        self.assertNotEqual(faded[0]["side"], followed[0]["side"])


if __name__ == "__main__":
    unittest.main()
