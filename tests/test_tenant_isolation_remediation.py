from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config.paths as paths
import config.settings_store as settings_store
from api.ws_scope import entry_visible_to_user
from api.routes.bot import _get_uid as bot_request_user_id
from api.routes.tickers import _get_uid as ticker_request_user_id
from broker.alpaca_core import AlpacaCoreMixin
from fastapi import HTTPException
from starlette.requests import Request
from trading.loop.lifecycle import run_trading_loop, stop_loop
from trading.state import get_user_state, reset_session_state


def _request_without_identity() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


class TenantIsolationRemediationTests(unittest.TestCase):
    def test_request_identity_helpers_fail_closed(self) -> None:
        for helper in (bot_request_user_id, ticker_request_user_id):
            with self.subTest(helper=helper.__module__):
                with self.assertRaises(HTTPException) as raised:
                    helper(_request_without_identity())
                self.assertEqual(401, raised.exception.status_code)

    def test_trading_loop_lifecycle_requires_explicit_user(self) -> None:
        self.assertIs(inspect.Signature.empty, inspect.signature(run_trading_loop).parameters["user_id"].default)
        self.assertIs(inspect.Signature.empty, inspect.signature(stop_loop).parameters["user_id"].default)

    def test_contextless_reset_uses_isolated_system_tenant(self) -> None:
        admin = get_user_state("admin")
        system = get_user_state("system")
        admin["session_pnl"] = 123.0
        system["session_pnl"] = 456.0

        reset_session_state()

        self.assertEqual(123.0, admin["session_pnl"])
        self.assertEqual(0.0, system["session_pnl"])

    def test_new_user_does_not_inherit_legacy_bot_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "bot_state.json"
            legacy.write_text(json.dumps({"account_balance": 9999.0}))
            with patch.object(paths, "_USER_DATA", root / "user_data"), patch.object(
                paths, "_LEGACY_BOT_STATE_PATH", legacy,
            ):
                state_path = paths.get_bot_state_path("new-user")

            self.assertFalse(state_path.exists())
            self.assertEqual(root / "user_data" / "new-user" / "bot_state.json", state_path)

    def test_new_user_does_not_inherit_legacy_settings_or_environment_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_settings = root / "user_settings.json"
            legacy_settings.write_text(json.dumps({"owner_only_marker": True}))
            with patch.object(paths, "_USER_DATA", root / "user_data"), patch.object(
                settings_store, "SETTINGS_PATH", legacy_settings,
            ), patch.object(settings_store, "ALPACA_API_KEY", "owner-key"), patch.object(
                settings_store, "ALPACA_SECRET_KEY", "owner-secret",
            ), patch.object(settings_store, "TRADIER_API_KEY", "owner-tradier"), patch.object(
                settings_store, "TRADIER_ACCOUNT_ID", "owner-account",
            ):
                new_settings = settings_store.get_settings("new-user")
                new_keys = settings_store.get_api_keys("new-user")
                admin_settings = settings_store.get_settings("admin")
                admin_keys = settings_store.get_api_keys("admin")

            self.assertNotIn("owner_only_marker", new_settings)
            self.assertEqual("", new_keys["alpaca_api_key"])
            self.assertEqual("", new_keys["tradier_api_key"])
            self.assertTrue(admin_settings["owner_only_marker"])
            self.assertEqual("owner-key", admin_keys["alpaca_api_key"])

    def test_websocket_log_filter_is_exact_and_fails_closed(self) -> None:
        self.assertTrue(entry_visible_to_user({"user_id": "alice"}, "alice"))
        self.assertFalse(entry_visible_to_user({"user_id": "alice"}, "bob"))
        self.assertFalse(entry_visible_to_user({}, "alice"))


class BrokerMarketTruthTests(unittest.TestCase):
    def test_authenticated_broker_failure_fails_market_closed(self) -> None:
        client = AlpacaCoreMixin.__new__(AlpacaCoreMixin)
        client.api_key = "user-key"
        client.base = "https://paper-api.alpaca.markets"
        with patch.object(client, "_get", side_effect=RuntimeError("network unavailable")), patch(
            "broker.alpaca_core._local_market_is_open", return_value=True,
        ):
            self.assertFalse(client.is_market_open())


if __name__ == "__main__":
    unittest.main()
