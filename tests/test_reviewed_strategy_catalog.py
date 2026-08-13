from __future__ import annotations

import unittest

from config.strategy_catalog import (
    REVIEWED_STRATEGIES, ensure_reviewed_ticker_coverage, is_allowed_ticker,
)


class ReviewedStrategyCatalogTests(unittest.TestCase):
    def test_scope_is_explicit_per_strategy_and_ticker(self) -> None:
        self.assertTrue(is_allowed_ticker("V2_ORB_PULLBACK", "TSLA"))
        self.assertFalse(is_allowed_ticker("V2_ORB_PULLBACK", "SPY"))
        self.assertTrue(is_allowed_ticker("V2_SPY_TREND_CONT", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_TREND_CONT", "QQQ"))
        self.assertTrue(is_allowed_ticker("V2_TSLA_NOISE_MOMENTUM", "TSLA"))
        self.assertFalse(is_allowed_ticker("V2_TSLA_NOISE_MOMENTUM", "SPY"))

    def test_scanner_list_is_preserved_and_covered_for_enabled_rules(self) -> None:
        self.assertEqual(
            ["QQQ", "NVDA", "TSLA", "SPY"],
            ensure_reviewed_ticker_coverage(
                ["QQQ", "NVDA"], {"V2_SPY_TREND_CONT", "V2_ORB_PULLBACK"},
            ),
        )

    def test_spy_trend_exit_matches_its_one_position_paid_data_selection(self) -> None:
        self.assertEqual(30, REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"].exit_minutes)

    def test_tsla_noise_exit_is_a_clock_time_not_a_duration(self) -> None:
        self.assertIsNone(REVIEWED_STRATEGIES["V2_TSLA_NOISE_MOMENTUM"].exit_minutes)


if __name__ == "__main__":
    unittest.main()
