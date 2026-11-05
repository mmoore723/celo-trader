import unittest
from unittest.mock import Mock, patch

import requests

from broker.tradier_orders import TradierOrdersMixin


class EarningsAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.client = TradierOrdersMixin()
        self.client.base = "https://example.invalid/v1"
        self.client.headers = {}

    def lookup(self, payload=None, status=200, error=None):
        response = Mock(status_code=status)
        response.json.return_value = payload
        with patch("broker.tradier_orders.requests.get", return_value=response, side_effect=error), \
                patch("broker.tradier_orders._debounced_log") as warning, \
                patch("broker.tradier_orders.log_event") as event:
            result = self.client.get_earnings("AAPL")
        return result, warning, event

    def test_http_errors_are_not_empty_calendars(self):
        for code in (301, 401, 403, 404, 429, 500):
            with self.subTest(code=code):
                result, warning, _ = self.lookup(status=code)
                self.assertIsNone(result)
                self.assertEqual(self.client.earnings_status["AAPL"]["reason"], f"HTTP {code}")
                warning.assert_called_once()

    def test_invalid_payloads_are_unavailable(self):
        for payload in ({}, None, {"security": {"calendar": {"event": None}}},
                        {"security": {"calendar": {"event": [{"type": "earnings", "date": "bad"}]}}}):
            self.assertIsNone(self.lookup(payload)[0])

    def test_timeout_is_unavailable(self):
        self.assertIsNone(self.lookup(error=requests.Timeout())[0])
        self.assertEqual(self.client.earnings_status["AAPL"]["reason"], "request timeout")

    def test_explicit_empty_is_available(self):
        result, warning, _ = self.lookup({"security": {"calendar": {"event": []}}})
        self.assertEqual(result, [])
        warning.assert_not_called()
        self.assertEqual(self.client.earnings_status["AAPL"]["status"], "available")

    def test_dates_and_recovery(self):
        self.lookup(status=404)
        payload = {"security": {"calendar": {"event": {"type": "earnings", "date": "2026-11-06"}}}}
        result, _, event = self.lookup(payload)
        self.assertEqual(result, ["2026-11-06"])
        event.assert_called_once()
        self.assertTrue(self.client.earnings_status["AAPL"]["checked_at"].endswith("+00:00"))
        self.assertEqual(self.lookup(payload)[2].call_count, 0)


if __name__ == "__main__":
    unittest.main()
