import json
import unittest
from unittest.mock import patch

from broker.alpaca_client import AlpacaClient
from broker.connection_health import get_connection_health


class _Alpaca:
    def get_account(self):
        return {"equity": 3958.52}


class _TradierSandbox:
    def get_account(self):
        return {"equity": 100000.0}


KEYS = {
    "alpaca_api_key": "complete-alpaca-key",
    "alpaca_secret_key": "complete-alpaca-secret",
    "tradier_api_key": "complete-sandbox-token",
    "tradier_market_api_key": "complete-production-token",
    "tradier_account_id": "VA123456",
    "tradier_live_account_id": "6YB84763",
}


class BrokerConnectionHealthTests(unittest.TestCase):
    @patch("broker.alpaca_core.AlpacaCoreMixin.get_account")
    def test_real_checker_builds_alpaca_client_from_supplied_credentials(self, account):
        account.return_value = {"equity": 3958.52}
        observed = {}

        def market_check(token):
            observed["token"] = token
            return {"ok": True}

        with patch.object(AlpacaClient, "__init__", autospec=True, return_value=None) as init:
            result = get_connection_health(
                {"broker_provider": "alpaca", "paper_trading": True},
                KEYS,
                market_validator=market_check,
            )

        init.assert_called_once_with(
            unittest.mock.ANY,
            paper=True,
            api_key=KEYS["alpaca_api_key"],
            secret_key=KEYS["alpaca_secret_key"],
        )
        self.assertEqual(KEYS["tradier_market_api_key"], observed["token"])
        self.assertTrue(result["ready"])

    def test_alpaca_paper_shows_production_prices_and_unused_sandbox(self):
        result = get_connection_health(
            {"broker_provider": "alpaca", "paper_trading": True},
            KEYS,
            alpaca_client=_Alpaca(),
            market_validator=lambda _token: {"ok": True},
        )

        statuses = {row["id"]: row["status"] for row in result["connections"]}
        self.assertTrue(result["ready"])
        self.assertEqual("connected", statuses["alpaca_execution"])
        self.assertEqual("connected", statuses["tradier_production_market"])
        self.assertEqual("not_used", statuses["tradier_sandbox_execution"])

    def test_invalid_production_token_is_visible_but_never_exposed(self):
        result = get_connection_health(
            {"broker_provider": "alpaca", "paper_trading": True},
            KEYS,
            alpaca_client=_Alpaca(),
            market_validator=lambda _token: {
                "ok": False,
                "detail": "Tradier rejected this production token.",
            },
        )

        self.assertFalse(result["ready"])
        encoded = json.dumps(result)
        self.assertIn("rejected", encoded)
        for secret in KEYS.values():
            self.assertNotIn(secret, encoded)

    def test_tradier_paper_requires_both_market_and_sandbox_connections(self):
        result = get_connection_health(
            {"broker_provider": "tradier", "paper_trading": True},
            KEYS,
            tradier_sandbox_client=_TradierSandbox(),
            market_validator=lambda _token: {"ok": True},
        )

        statuses = {row["id"]: row["status"] for row in result["connections"]}
        self.assertTrue(result["ready"])
        self.assertEqual("not_used", statuses["alpaca_execution"])
        self.assertEqual("connected", statuses["tradier_production_market"])
        self.assertEqual("connected", statuses["tradier_sandbox_execution"])


if __name__ == "__main__":
    unittest.main()
