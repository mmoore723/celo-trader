from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock, patch
import pandas as pd
from broker import earnings_calendar as cal
from broker.tradier_orders import TradierOrdersMixin


class CalendarTests(TestCase):
    def setUp(self):
        self.ticker = Mock()
        self.ticker.get_info.return_value = {"quoteType": "EQUITY"}
        self.ticker.get_calendar.return_value = {"Earnings Date": [date(2099, 1, 1)]}
        self.ticker.get_earnings_dates.return_value = pd.DataFrame(
            {"EPS": [1, 2]}, index=pd.to_datetime(["2020-01-01", "2099-01-01"]).tz_localize("America/New_York"))

    def fetch(self):
        with patch("yfinance.Ticker", return_value=self.ticker):
            return cal.fetch("AAPL")

    def test_valid_dates(self):
        result = self.fetch()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["dates"], ["2020-01-01", "2099-01-01"])
        self.assertTrue(result["checked_at"].endswith("+00:00"))

    def test_verified_etf(self):
        self.ticker.get_info.return_value = {"quoteType": "ETF"}
        self.assertEqual(self.fetch()["status"], "not_applicable")
        self.ticker.get_earnings_dates.assert_not_called()

    def test_missing_type(self):
        self.ticker.get_info.return_value = {}
        self.assertIsNone(self.fetch()["dates"])

    def test_missing_history(self):
        self.ticker.get_earnings_dates.return_value = None
        self.assertIsNone(self.fetch()["dates"])

    def test_missing_upcoming(self):
        self.ticker.get_calendar.return_value = {}
        self.assertIsNone(self.fetch()["dates"])

    def test_missing_timezone(self):
        self.ticker.get_earnings_dates.return_value.index = pd.to_datetime(["2020-01-01", "2099-01-01"])
        self.assertIsNone(self.fetch()["dates"])

    def test_errors_are_sanitized(self):
        self.ticker.get_info.side_effect = RuntimeError("private cookie")
        result = self.fetch()
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private cookie", str(result))

    def test_refresh_deduplicates(self):
        future = Future()
        with patch.object(cal, "_cache", {}), patch.object(cal, "_pending", {}), \
                patch.object(cal._pool, "submit", return_value=future) as submit:
            self.assertEqual(cal.snapshot("AAPL")["status"], "loading")
            cal.snapshot("AAPL")
            submit.assert_called_once()
            future.set_result(cal._result("available", dates=["2099-01-01"]))
            self.assertEqual(cal.snapshot("AAPL")["dates"], ["2099-01-01"])

    def test_stale_result_not_used(self):
        stale = cal._result("available", dates=["2099-01-01"])
        stale["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = Future()
        future.set_result(stale)
        with patch.object(cal, "_cache", {}), patch.object(cal, "_pending", {"AAPL": future}), \
                patch.object(cal._pool, "submit", return_value=Future()):
            self.assertEqual(cal.snapshot("AAPL")["status"], "loading")

    def test_bounded_queue(self):
        with patch.object(cal, "_cache", {}), patch.object(cal, "_pending", {str(i): Future() for i in range(32)}):
            self.assertEqual(cal.snapshot("AAPL")["reason"], "Calendar worker queue is full")

    def test_warning_and_recovery(self):
        client = TradierOrdersMixin()
        with patch.object(cal, "snapshot", return_value=cal._result("loading", "pending")), \
                patch("broker.tradier_orders._debounced_log") as warning:
            self.assertIsNone(client.get_earnings("AAPL"))
            warning.assert_called_once()
        with patch.object(cal, "snapshot", return_value=cal._result("available", dates=["2099-01-01"])), \
                patch("broker.tradier_orders.log_event") as event:
            self.assertEqual(client.get_earnings("AAPL"), ["2099-01-01"])
            client.get_earnings("AAPL")
            event.assert_called_once()
