from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from broker.tradier_broker import TradierBrokerClient
from broker.tradier_market import TradierMarketMixin, _hourly, _utc_bar_time
from trading.controls.panic import _flatten_with_confirmed_fills
from trading.entry.tick import _entry_quote_is_fresh


class _MarketClient(TradierMarketMixin):
    api_key = "live-token"

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        del params
        return self.responses[endpoint]


class TradierMarketTests(unittest.TestCase):
    def test_naive_tradier_bar_time_is_eastern_and_normalized_to_utc(self):
        self.assertEqual(_utc_bar_time("2026-09-01T09:30:00"), "2026-09-01T13:30:00Z")

    def test_hourly_bars_are_anchored_at_market_open(self):
        rows = [
            {"t": "2026-09-01T13:30:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100, "vw": 10.2},
            {"t": "2026-09-01T13:45:00Z", "o": 10.5, "h": 12, "l": 10, "c": 11.5, "v": 300, "vw": 11.2},
            {"t": "2026-09-01T14:30:00Z", "o": 11.5, "h": 13, "l": 11, "c": 12.5, "v": 50, "vw": 12.1},
        ]
        bars = _hourly(rows)
        self.assertEqual(2, len(bars))
        self.assertEqual((10, 12, 9, 11.5, 400), tuple(bars[0][key] for key in "ohlcv"))

    @patch("broker.tradier_market.time.time", return_value=1_000_000_000.0)
    def test_quote_age_is_carried_into_normalized_quote(self, _clock):
        client = _MarketClient({
            "/markets/quotes": {"quotes": {"quote": {
                "symbol": "SPY", "bid": 600, "ask": 600.1, "last": 600.05,
                "bid_date": 999_999_990_000,
            }}},
        })
        quote = client.get_latest_quote("SPY")
        self.assertEqual(10.0, quote["quote_age_seconds"])


class TradierCutoverTests(unittest.TestCase):
    def _clients(self, *, quote_age: float = 5.0, account_error: Exception | None = None):
        execution = SimpleNamespace(
            base="https://sandbox.tradier.com/v1",
            headers={}, account_id="paper-account", api_key="sandbox-token",
            last_rejection_reason=None,
            get_account=Mock(
                side_effect=account_error,
                return_value={"equity": 1000.0, "buying_power": 1000.0},
            ),
            get_positions=Mock(return_value=[]),
            get_orders=Mock(return_value=[]),
            place_option_order=Mock(return_value={"id": "1", "filled_qty": 1}),
        )
        market = SimpleNamespace(
            base="https://api.tradier.com/v1",
            is_market_open=Mock(return_value=True),
            get_latest_quote=Mock(return_value={
                "bp": 600.0, "ap": 600.1, "quote_age_seconds": quote_age,
            }),
            get_option_quote=Mock(return_value={"bid": 1.0, "ask": 1.1, "mid": 1.05}),
        )
        return execution, market

    def test_one_boundary_routes_market_data_and_both_order_sides_to_tradier(self):
        execution, market = self._clients()
        broker = TradierBrokerClient(execution, market, paper=True)
        broker.get_option_quote("SPY260904C00650000")
        broker.place_option_order(symbol="SPY260904C00650000", qty=1, side="buy", position_intent="buy_to_open")
        broker.place_option_order(symbol="SPY260904C00650000", qty=1, side="sell", position_intent="sell_to_close")
        market.get_option_quote.assert_called_once()
        self.assertEqual(2, execution.place_option_order.call_count)
        self.assertEqual("buy_to_open", execution.place_option_order.call_args_list[0].kwargs["position_intent"])
        self.assertEqual("sell_to_close", execution.place_option_order.call_args_list[1].kwargs["position_intent"])

    def test_readiness_rejects_delayed_market_data(self):
        execution, market = self._clients(quote_age=901.0)
        result = TradierBrokerClient(execution, market, paper=True).readiness()
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["market_quote_freshness"]["passed"])

    def test_readiness_rejects_unavailable_balances(self):
        execution, market = self._clients(account_error=RuntimeError("balance unavailable"))
        result = TradierBrokerClient(execution, market, paper=True).readiness()
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["account_balance"]["passed"])

    def test_readiness_accepts_complete_fresh_read_only_surface(self):
        execution, market = self._clients()
        result = TradierBrokerClient(execution, market, paper=True).readiness()
        self.assertTrue(result["ready"])

    def test_factory_separates_sandbox_execution_from_live_market_data(self):
        # Import-local config calls are tested by patching their source module.
        from broker.factory import get_tradier_broker
        keys = {
            "tradier_api_key": "sandbox-token",
            "tradier_account_id": "sandbox-account",
            "tradier_market_api_key": "live-token",
            "tradier_live_account_id": "live-account",
        }
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "config.get_api_keys", return_value=keys,
        ):
            paper_broker, paper_market = get_tradier_broker(paper=True)
            live_broker, live_market = get_tradier_broker(paper=False)
        self.assertEqual("sandbox-token", paper_broker.execution.api_key)
        self.assertEqual("sandbox-account", paper_broker.execution.account_id)
        self.assertEqual("live-token", paper_market.api_key)
        self.assertEqual("live-token", live_broker.execution.api_key)
        self.assertEqual("live-account", live_broker.execution.account_id)
        self.assertIs(live_broker.market, live_market)


class ExecutionSafetyTests(unittest.TestCase):
    def test_entry_quote_requires_a_recent_broker_timestamp(self):
        self.assertTrue(_entry_quote_is_fresh({"quote_age_seconds": 15}))
        self.assertFalse(_entry_quote_is_fresh({"quote_age_seconds": 901}))
        self.assertFalse(_entry_quote_is_fresh({}))

    @patch("trading.position_manager.close._close_position")
    @patch("database.get_open_trades", side_effect=[
        [{"id": 1, "contract_symbol": "SPY260904C00650000", "entry_price": 1.0}],
        [],
    ])
    def test_panic_closes_local_trade_only_through_confirmed_fill_path(self, _trades, close_position):
        broker = SimpleNamespace(get_positions=Mock(return_value=[]))
        market = SimpleNamespace(get_option_quote=Mock(return_value={"bid": 0.9, "mid": 0.95}))
        self.assertTrue(_flatten_with_confirmed_fills(broker, market, reason="panic"))
        close_position.assert_called_once()

    @patch("trading.position_manager.close._close_position")
    @patch("database.get_open_trades", side_effect=[
        [{"id": 1, "contract_symbol": "SPY260904C00650000", "entry_price": 1.0}],
        [{"id": 1}],
    ])
    def test_panic_fails_closed_when_exit_is_unconfirmed(self, _trades, _close_position):
        broker = SimpleNamespace(get_positions=Mock(return_value=[]))
        market = SimpleNamespace(get_option_quote=Mock(return_value=None))
        self.assertFalse(_flatten_with_confirmed_fills(broker, market, reason="panic"))


if __name__ == "__main__":
    unittest.main()
