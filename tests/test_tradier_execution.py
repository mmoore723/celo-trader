from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from broker.tradier_execution import TradierExecutionMixin, _underlying_from_occ


class _TradierExecutionClient(TradierExecutionMixin):
    def __init__(self):
        self.api_key = "test-token"
        self.account_id = "VA000001"
        self.base = "https://sandbox.tradier.com/v1"
        self.headers = {"Authorization": "Bearer test-token", "Accept": "application/json"}
        self.responses: dict[str, dict] = {}

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        del params
        return self.responses.get(endpoint, {})


class TradierExecutionTests(unittest.TestCase):
    def test_underlying_is_derived_from_occ_symbol(self):
        self.assertEqual(_underlying_from_occ("SPY260904C00650000"), "SPY")
        self.assertEqual(_underlying_from_occ("AMZN260904P00180000"), "AMZN")

    def test_account_response_is_normalized(self):
        client = _TradierExecutionClient()
        client.responses["/accounts/VA000001/balances"] = {
            "balances": {
                "total_equity": 1234.50,
                "total_cash": 900.25,
                "option_buying_power": 777.00,
            }
        }
        self.assertEqual(
            client.get_account(),
            {
                "equity": 1234.5,
                "buying_power": 777.0,
                "cash": 900.25,
                "options_buying_power": 777.0,
            },
        )

    def test_missing_balance_fails_closed(self):
        client = _TradierExecutionClient()
        client.responses["/accounts/VA000001/balances"] = {}
        with self.assertRaisesRegex(RuntimeError, "no usable account balances"):
            client.get_account()

    def test_single_position_object_is_normalized(self):
        client = _TradierExecutionClient()
        client.responses["/accounts/VA000001/positions"] = {
            "positions": {
                "position": {
                    "symbol": "SPY260904C00650000",
                    "quantity": 2.0,
                    "cost_basis": 400.0,
                }
            }
        }
        positions = client.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["qty"], 2)
        self.assertEqual(positions[0]["avg_entry_price"], 2.0)

    @patch("broker.tradier_execution.log_event")
    @patch("broker.tradier_execution._record_flow")
    @patch("broker.tradier_execution.requests.post")
    def test_submission_maps_side_and_returns_only_confirmed_fill(
        self, post, _record, _log_event
    ):
        response = Mock()
        response.text = '{"order":{"id":123,"status":"ok"}}'
        response.json.return_value = {"order": {"id": 123, "status": "ok"}}
        response.raise_for_status.return_value = None
        post.return_value = response
        client = _TradierExecutionClient()
        client._wait_for_tradier_fill = Mock(return_value={
            "id": "123", "status": "filled", "filled_qty": 1,
            "filled_avg_price": 2.05, "confirmed_fill_price": 2.05,
        })

        result = client.place_option_order(
            symbol="SPY260904C00650000",
            qty=1,
            side="buy",
            order_type="limit",
            limit_price=2.05,
            position_intent="buy_to_open",
            order_context={"ticker": "SPY", "intent_id": "intent-123"},
        )

        self.assertEqual(result["confirmed_fill_price"], 2.05)
        payload = post.call_args.kwargs["data"]
        self.assertEqual(payload["symbol"], "SPY")
        self.assertEqual(payload["option_symbol"], "SPY260904C00650000")
        self.assertEqual(payload["side"], "buy_to_open")
        self.assertEqual(payload["price"], "2.05")
        self.assertTrue(payload["tag"].startswith("celo-intent-123"))

    @patch("broker.tradier_execution._record_flow")
    @patch("broker.tradier_execution.monotonic", side_effect=[0.0, 1.0, 2.0])
    def test_filled_status_normalizes_tradier_fields(self, _clock, _record):
        client = _TradierExecutionClient()
        client.get_order = Mock(return_value={
            "id": 123,
            "status": "filled",
            "exec_quantity": 2.0,
            "avg_fill_price": 1.75,
        })
        result = client._wait_for_tradier_fill(
            order_id="123",
            flow_base={"attempt_id": "attempt"},
            qty=2,
            side="buy_to_open",
            limit_price=1.75,
            step_to_price=None,
            max_acceptable_price=None,
            allow_market_fallback=False,
            max_wait_seconds=30,
        )
        self.assertEqual(result["filled_qty"], 2)
        self.assertEqual(result["confirmed_fill_price"], 1.75)
        self.assertFalse(result["partial_fill"])

    @patch("broker.tradier_execution._record_flow")
    @patch("broker.tradier_execution.monotonic", side_effect=[0.0, 1.0])
    def test_terminal_partial_fill_is_preserved(self, _clock, _record):
        client = _TradierExecutionClient()
        client.get_order = Mock(return_value={
            "id": 123,
            "status": "canceled",
            "exec_quantity": 1.0,
            "avg_fill_price": 1.80,
        })
        result = client._wait_for_tradier_fill(
            order_id="123",
            flow_base={"attempt_id": "attempt"},
            qty=2,
            side="buy_to_open",
            limit_price=1.80,
            step_to_price=None,
            max_acceptable_price=None,
            allow_market_fallback=False,
            max_wait_seconds=30,
        )
        self.assertEqual(result["filled_qty"], 1)
        self.assertTrue(result["partial_fill"])

    @patch("broker.tradier_execution._record_flow")
    @patch("broker.tradier_execution.monotonic", side_effect=[0.0, 31.0])
    def test_timeout_without_execution_returns_none_after_confirmed_cancel(self, _clock, _record):
        client = _TradierExecutionClient()
        client.cancel_order = Mock(return_value=True)
        client.get_order = Mock(return_value={
            "id": 123, "status": "canceled", "exec_quantity": 0,
        })
        result = client._wait_for_tradier_fill(
            order_id="123",
            flow_base={"attempt_id": "attempt"},
            qty=1,
            side="buy_to_open",
            limit_price=1.80,
            step_to_price=None,
            max_acceptable_price=None,
            allow_market_fallback=False,
            max_wait_seconds=30,
        )
        self.assertIsNone(result)
        client.cancel_order.assert_called_once_with("123")


if __name__ == "__main__":
    unittest.main()
