import unittest

from research.jobs.screen_cross_ticker_afternoon_compression import passes


class CrossTickerCompressionTests(unittest.TestCase):
    def test_pass_requires_positive_typical_trade(self):
        value = {"trades": 20, "average_return_pct": 1, "median_return_pct": -0.1, "profit_factor": 2}
        self.assertFalse(passes(value))

    def test_pass_requires_sample_floor(self):
        value = {"trades": 14, "average_return_pct": 1, "median_return_pct": 1, "profit_factor": 2}
        self.assertFalse(passes(value))


if __name__ == "__main__":
    unittest.main()
