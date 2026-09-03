import unittest
from unittest.mock import patch

from trading.research_collection import collect_watchlist_session_bars


class _BarsClient:
    def __init__(self):
        self.calls = []

    def get_session_bars(self, ticker, timeframe):
        self.calls.append((ticker, timeframe))
        if ticker == "FAIL":
            return [], True, False
        return [{
            "t": "2026-09-03T14:30:00Z",
            "o": 100.0,
            "h": 101.0,
            "l": 99.5,
            "c": 100.5,
            "v": 1000,
        }], False, True


class ResearchCollectionTests(unittest.TestCase):
    @patch("trading.research_collection.record_scanner_candles")
    def test_every_unique_ticker_is_fetched_before_entry_gates(self, record):
        client = _BarsClient()

        archived = collect_watchlist_session_bars(
            client,
            ["spy", "QQQ", "SPY", "FAIL"],
            broker_account_id="paper-account",
        )

        self.assertEqual(
            [("SPY", "1Min"), ("QQQ", "1Min"), ("FAIL", "1Min")],
            client.calls,
        )
        self.assertEqual({"SPY", "QQQ"}, archived)
        self.assertEqual(2, record.call_count)
        self.assertEqual("paper-account", record.call_args.kwargs["broker_account_id"])


if __name__ == "__main__":
    unittest.main()
