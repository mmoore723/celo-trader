import unittest

from config.market_constants import TICKER_UNIVERSE
from config.strategy_catalog import is_allowed_ticker


class MarketUniverseTests(unittest.TestCase):
    def test_amzn_is_observed_without_becoming_order_eligible(self):
        self.assertIn("AMZN", TICKER_UNIVERSE)
        self.assertFalse(is_allowed_ticker("V2_SPY_TREND_CONT", "AMZN"))
        self.assertFalse(is_allowed_ticker("V2_ORB_PULLBACK", "AMZN"))


if __name__ == "__main__":
    unittest.main()
