from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from starlette.requests import Request

from api.routes.bot import get_status, start_bot


def _request(user_id: str = "guest") -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.user_id = user_id
    return request


EMPTY_KEYS = {
    "alpaca_api_key": "",
    "alpaca_secret_key": "",
    "tradier_api_key": "",
    "tradier_market_api_key": "",
    "tradier_account_id": "",
    "tradier_live_account_id": "",
}


class BrokerConnectionStatusTests(unittest.TestCase):
    def test_reconciliation_state_is_exposed_as_global_broker_alert(self) -> None:
        alignment = {
            "detected_at": "2026-08-20T08:00:00-04:00",
            "issues": [{
                "trade_id": 186,
                "symbol": "SPY260821P00775000",
                "message": "Trade #186 is open in the journal, but Alpaca is flat.",
            }],
            "positions": [],
        }
        connected_keys = {
            **EMPTY_KEYS,
            "alpaca_api_key": "paper-key",
            "alpaca_secret_key": "paper-secret",
            "tradier_market_api_key": "live-market-data-key",
        }
        state = {
            "running": True,
            "mode": "paper",
            "account_balance": 5000.0,
            "day_start_balance": 5000.0,
            "session_pnl": 0.0,
            "options_buying_power": 5000.0,
            "ghost_position_alert": alignment,
        }
        with patch("api.routes.bot._read_bot_state", return_value=state), patch(
            "config.get_api_keys", return_value=connected_keys,
        ), patch(
            "config.get_settings", return_value={"paper_trading": True},
        ), patch(
            "trading.state.get_user_state", return_value=dict(state),
        ), patch(
            "trading.state._get_lock", return_value=threading.Lock(),
        ), patch(
            "config.get_maintenance_state",
            return_value={"maintenance_mode": False, "collection_only": False},
        ):
            status = get_status(_request())

        self.assertTrue(status.ghost_position_detected)
        self.assertTrue(status.broker_connected)
        self.assertEqual(1, len(status.broker_alerts))
        self.assertEqual("alpaca reconciliation", status.broker_alerts[0]["broker"])
        self.assertIn("Trade #186", status.broker_alerts[0]["last_error"])

    def test_disconnected_account_never_exposes_starting_capital_as_balance(self) -> None:
        stale_state = {
            "running": True,
            "mode": "paper",
            "account_balance": 5000.0,
            "day_start_balance": 5000.0,
            "session_pnl": 25.0,
            "options_buying_power": 5000.0,
        }
        with patch("api.routes.bot._read_bot_state", return_value=stale_state), patch(
            "config.get_api_keys", return_value=EMPTY_KEYS,
        ), patch(
            "config.get_settings",
            return_value={"paper_trading": True, "last_known_balance": 5000.0},
        ), patch(
            "trading.state.get_user_state", return_value=dict(stale_state),
        ), patch(
            "trading.state._get_lock", return_value=threading.Lock(),
        ), patch(
            "config.get_maintenance_state",
            return_value={"maintenance_mode": False, "collection_only": False},
        ):
            status = get_status(_request())

        self.assertFalse(status.broker_connected)
        self.assertFalse(status.running)
        self.assertEqual("paper", status.mode)
        self.assertEqual(0.0, status.account_balance)
        self.assertEqual(0.0, status.day_start_balance)
        self.assertEqual(0.0, status.options_buying_power)
        self.assertEqual(0.0, status.session_pnl)

    def test_start_is_rejected_before_a_thread_is_created_when_keys_are_missing(self) -> None:
        with patch("config.get_api_keys", return_value=EMPTY_KEYS), patch(
            "config.get_settings", return_value={"paper_trading": True},
        ):
            response = start_bot(_request("no-keys"))

        self.assertFalse(response.ok)
        self.assertIn("Broker connection required", response.message)


if __name__ == "__main__":
    unittest.main()
