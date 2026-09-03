import unittest
from unittest.mock import patch

import requests

from broker.credential_validation import validate_tradier_market_token


class TradierCredentialValidationTests(unittest.TestCase):
    @patch("broker.credential_validation.TradierClient._get")
    def test_accepts_production_token_only_after_positive_quote(self, request):
        request.return_value = {
            "quotes": {"quote": {"symbol": "SPY", "bid": 500.0, "ask": 500.02}}
        }

        result = validate_tradier_market_token("production-token")

        self.assertTrue(result["ok"])
        self.assertEqual("verified", result["code"])

    @patch("broker.credential_validation.TradierClient._get")
    def test_explains_rejected_production_token(self, request):
        response = requests.Response()
        response.status_code = 401
        request.side_effect = requests.HTTPError(response=response)

        result = validate_tradier_market_token("rejected-token")

        self.assertFalse(result["ok"])
        self.assertEqual("unauthorized", result["code"])
        self.assertIn("Production Account Access", result["detail"])


if __name__ == "__main__":
    unittest.main()
