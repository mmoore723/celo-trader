from __future__ import annotations

import unittest

from config.strategy_catalog import ensure_reviewed_ticker_coverage, is_allowed_ticker


class ReviewedStrategyCatalogTests(unittest.TestCase):
    def test_scope_is_explicit_per_strategy_and_ticker(self) -> None:
        self.assertTrue(is_allowed_ticker("V2_ORB_PULLBACK", "TSLA"))
        self.assertFalse(is_allowed_ticker("V2_ORB_PULLBACK", "SPY"))
        self.assertTrue(is_allowed_ticker("V2_SPY_TREND_CONT", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_TREND_CONT", "QQQ"))

    def test_scanner_list_is_preserved_and_covered_for_enabled_rules(self) -> None:
        self.assertEqual(
            ["QQQ", "NVDA", "TSLA", "SPY"],
            ensure_reviewed_ticker_coverage(
                ["QQQ", "NVDA"], {"V2_SPY_TREND_CONT", "V2_ORB_PULLBACK"},
            ),
        )


if __name__ == "__main__":
    unittest.main()
