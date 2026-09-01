from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request

from api.models.settings import Settings
from api.routes.settings import save_settings_endpoint


class BrokerActivationTests(unittest.TestCase):
    @staticmethod
    def _payload(**overrides) -> Settings:
        values = {
            "broker_provider": "tradier", "paper_trading": True,
            "risk_pct": 5.0, "risk_auto": True, "growth_mode": False,
            "flip_trading_enabled": True, "max_concurrent_positions": 2,
            "rr_ratio_mode": "auto", "watchlist": ["SPY"],
        }
        values.update(overrides)
        return Settings(**values)

    def test_settings_schema_keeps_broker_and_paper_mode(self):
        payload = self._payload(paper_trading=False)
        self.assertEqual("tradier", payload.model_dump()["broker_provider"])
        self.assertFalse(payload.model_dump()["paper_trading"])

    def test_tradier_activation_is_rejected_before_settings_are_saved(self):
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.user_id = "alice"
        current = self._payload(broker_provider="alpaca").model_dump()
        broker = Mock()
        broker.readiness.return_value = {
            "ready": False,
            "checks": {"account_balance": {"passed": False, "detail": "HTTP 500"}},
        }
        unlocked = Mock()
        unlocked.locked.return_value = False
        with patch("config.get_settings", return_value=current), patch(
            "config.save_settings",
        ) as save_settings, patch("trading.state._get_lock", return_value=unlocked), patch(
            "broker.get_tradier_broker", return_value=(broker, Mock()),
        ):
            with self.assertRaises(HTTPException) as raised:
                save_settings_endpoint(self._payload(), request)
        self.assertEqual(409, raised.exception.status_code)
        self.assertIn("readiness check", raised.exception.detail)
        save_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
