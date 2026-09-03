import unittest

from scanner.universe import (
    build_collection_universe,
    complete_daily_collection_universe,
)


class ScannerCollectionUniverseTests(unittest.TestCase):
    def test_pins_and_anchors_do_not_displace_dynamic_candidates(self):
        dynamic = ["SNOW", "ZS", "DDOG", "MRVL", "NET", "TWLO", "PLTR", "TSLA", "SLB", "MRK"]
        actual = build_collection_universe(
            user_pins=["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "AMD", "META", "AMZN", "NFLX"],
            dynamic_tickers=dynamic,
        )

        self.assertEqual(18, len(actual))
        self.assertEqual(["SPY", "QQQ", "NVDA", "TSLA"], actual[:4])
        self.assertTrue(set(dynamic).issubset(actual))

    def test_old_daily_file_is_completed_from_displayed_scan_details(self):
        daily = {
            "universe": ["SPY", "QQQ", "AMZN", "SNOW"],
            "scan_details": [
                {"ticker": "SNOW"},
                {"ticker": "ZS"},
                {"ticker": "DDOG"},
            ],
        }

        actual = complete_daily_collection_universe(daily, user_pins=["amzn"])

        self.assertEqual(["AMZN", "SPY", "QQQ", "SNOW", "ZS", "DDOG"], actual)
        self.assertEqual(len(actual), len(set(actual)))


if __name__ == "__main__":
    unittest.main()
