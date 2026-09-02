from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from api.routes.ws import _normalize_status_state
from broker.alpaca_core import AlpacaCoreMixin
from trading.session_equity import resolve_day_start_balance


class SessionEquityTests(unittest.TestCase):
    def test_broker_previous_close_overrides_midday_restart_balance(self) -> None:
        value, source = resolve_day_start_balance(
            {"equity": 3958.80, "last_equity": 4359.10},
            current_equity=3958.80,
            persisted_balance=4080.90,
        )
        self.assertEqual(4359.10, value)
        self.assertEqual("broker_previous_close", source)

    def test_persisted_open_is_used_when_broker_has_no_previous_close(self) -> None:
        value, source = resolve_day_start_balance(
            {"equity": 980.00},
            current_equity=980.00,
            persisted_balance=1000.00,
        )
        self.assertEqual(1000.00, value)
        self.assertEqual("persisted_day_open", source)

    def test_alpaca_account_preserves_last_equity(self) -> None:
        client = AlpacaCoreMixin.__new__(AlpacaCoreMixin)
        client.api_key = "paper-key"
        client.base = "https://paper-api.alpaca.markets"
        client._get = lambda _url: {
            "equity": "3958.8", "last_equity": "4359.1",
            "buying_power": "15835.2", "cash": "3958.8",
            "options_buying_power": "3958.8",
        }
        account = client.get_account()
        self.assertEqual(4359.1, account["last_equity"])

    def test_websocket_restores_day_open_instead_of_replacing_http_status(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        settings = {
            "broker_provider": "alpaca",
            "paper_trading": True,
            "last_known_balance": 3958.80,
            f"day_start_{today}": 4359.10,
        }
        keys = {
            "alpaca_api_key": "paper-key",
            "alpaca_secret_key": "paper-secret",
            "tradier_api_key": "market-key",
            "tradier_market_api_key": "live-market-key",
            "tradier_account_id": "paper-account",
        }
        state = {
            "running": True,
            "account_balance": 3958.80,
            "day_start_balance": None,
            "session_pnl": -122.10,
        }
        with patch("config.get_api_keys", return_value=keys), patch(
            "config.get_settings", return_value=settings,
        ), patch("trading.state.get_user_state", return_value={}):
            normalized = _normalize_status_state(state, "admin")

        self.assertEqual(4359.10, normalized["day_start_balance"])
        self.assertEqual(-400.30, normalized["session_pnl"])


if __name__ == "__main__":
    unittest.main()
