import unittest

from broker.alpaca_core import AlpacaCoreMixin
from scanner.premarket import (
    _balanced_shortlist,
    _optionable_scan_pool,
    _strategy_fit_labels,
)


class BroadOptionableScannerTests(unittest.TestCase):
    def test_asset_discovery_keeps_only_active_tradable_non_otc_symbols(self):
        client = AlpacaCoreMixin.__new__(AlpacaCoreMixin)
        client.api_key = "test"
        client.base = "https://paper-api.alpaca.markets"
        client._get = lambda *_args, **_kwargs: [
            {"symbol": "AAPL", "tradable": True, "exchange": "NASDAQ"},
            {"symbol": "BRK.B", "tradable": True, "exchange": "NYSE"},
            {"symbol": "OTCX", "tradable": True, "exchange": "OTC"},
            {"symbol": "HALT", "tradable": False, "exchange": "NYSE"},
        ]
        self.assertEqual(["AAPL", "BRK.B"], client.get_optionable_assets())

    def test_live_asset_list_replaces_the_small_hard_coded_pool(self):
        class FakeAlpaca:
            def get_optionable_assets(self):
                return ["ZZZZ", "AAPL", "TQQQ"]

        pool, source = _optionable_scan_pool(FakeAlpaca(), ["MSFT"])
        self.assertEqual("Alpaca active optionable assets", source)
        self.assertIn("ZZZZ", pool)
        self.assertIn("MSFT", pool)
        self.assertNotIn("TQQQ", pool)

    def test_strategy_fit_recognizes_compression_inside_day_and_trend(self):
        bars = [
            {"h": 102, "l": 98}, {"h": 103, "l": 97}, {"h": 102, "l": 98},
            {"h": 102, "l": 98}, {"h": 102, "l": 98}, {"h": 104, "l": 96},
            {"h": 101, "l": 99},
        ]
        labels = _strategy_fit_labels(bars, gap_pct=1.2, atr_usd=2.2, price=100)
        self.assertIn("compressed-range ORB", labels)
        self.assertIn("inside-day ORB", labels)
        self.assertIn("trend / pullback", labels)
        self.assertIn("volatility", labels)

    def test_shortlist_preserves_multiple_strategy_families(self):
        rows = [
            {"ticker": "GAP1", "score": 9, "strategy_fit": ["trend / pullback"]},
            {"ticker": "GAP2", "score": 8, "strategy_fit": ["trend / pullback"]},
            {"ticker": "NR7", "score": 7, "strategy_fit": ["compressed-range ORB"]},
            {"ticker": "INSIDE", "score": 6, "strategy_fit": ["inside-day ORB"]},
            {"ticker": "VOL", "score": 5, "strategy_fit": ["volatility"]},
        ]
        chosen = _balanced_shortlist(rows, 4)
        labels = {label for row in chosen for label in row["strategy_fit"]}
        self.assertIn("compressed-range ORB", labels)
        self.assertIn("inside-day ORB", labels)
        self.assertIn("volatility", labels)


if __name__ == "__main__":
    unittest.main()
