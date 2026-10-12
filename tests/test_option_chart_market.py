from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock

from api.option_chart_market import daily_option_candles, current_option_bid

SYMBOL = "SPY261016P00770000"
NOW = datetime(2026, 10, 12, 20, tzinfo=timezone.utc)


class OptionChartMarketTests(TestCase):
    def test_history_requests_exact_occ_daily_not_underlying(self):
        client = Mock()
        client._get.return_value = {"history": {"day": {
            "date": "2026-10-12", "open": 4, "high": 5, "low": 3, "close": 4.5, "volume": 12,
        }}}
        candles = daily_option_candles(client, SYMBOL.lower(), NOW, NOW)
        self.assertEqual(client._get.call_args.args, ("/markets/history", {
            "symbol": SYMBOL, "interval": "daily", "start": "2026-10-12", "end": "2026-10-12",
        }))
        self.assertEqual(candles[0]["open"], 4)
        self.assertEqual(candles[0]["time"], datetime(2026, 10, 12, 4, tzinfo=timezone.utc).timestamp())

    def test_no_stock_fallback_and_no_invented_missing_candles(self):
        client = Mock()
        with self.assertRaises(ValueError):
            daily_option_candles(client, "SPY", NOW, NOW)
        client._get.assert_not_called()
        client._get.return_value = {"history": None}
        self.assertEqual(daily_option_candles(client, SYMBOL, NOW, NOW), [])
        client._get.return_value = {"history": {"day": [{"date": "2026-10-12", "open": float("nan"), "high": 5, "low": 3, "close": 4}]}}
        self.assertEqual(daily_option_candles(client, SYMBOL, NOW, NOW), [])

    def test_quote_uses_exact_symbol_and_bid_exchange_timestamp(self):
        client = Mock()
        quote = dict(source_symbol=SYMBOL, bid=4, ask=4.1, bid_date=NOW.timestamp()*1000, ask_date=(NOW.timestamp()+30)*1000)
        client.get_option_quote.return_value = quote
        self.assertEqual(current_option_bid(client, SYMBOL, NOW.timestamp()), dict(time=NOW.timestamp(), bid=4, ask=4.1))
        for change in [dict(source_symbol="SPY"), dict(bid_date=None), dict(bid=-1), dict(ask=3), dict(bid=float("nan"))]:
            client.get_option_quote.return_value = {**quote, **change}
            self.assertIsNone(current_option_bid(client, SYMBOL, NOW.timestamp()))
