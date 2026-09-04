"""Offline regressions: modified feed prices must never drive order repricing."""
from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from broker.alpaca_bars import AlpacaBarsMixin
from broker.alpaca_orders import AlpacaOrdersMixin
from broker.tradier_chain import TradierChainMixin

SYMBOL = "SPY260908C00770000"


def quote(**overrides):
    return {"bp": 4.38, "ap": 4.40, "feed": "opra", "symbol": SYMBOL,
            "t": datetime.now(timezone.utc).isoformat(), **overrides}


class OptionQuoteAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.flow = patch("broker.alpaca_orders._record_flow").start()
        patch("broker.alpaca_orders.log_event").start()
        self.addCleanup(patch.stopall)
        self.broker = AlpacaOrdersMixin()
        self.broker.base = "https://paper-api.alpaca.markets"
        self.broker.api_key = "offline-only"
        self.broker.get_latest_option_quote = Mock(return_value=quote())
        self.broker._post = Mock(return_value={"id": "test-order"})
        self.broker._wait_for_fill = Mock(return_value={
            "id": "test-order", "status": "filled", "filled_qty": "2",
            "filled_avg_price": "4.35",
        })

    def sell(self, **kwargs):
        return self.broker.place_option_order(
            SYMBOL, 2, "sell", limit_price=4.33, step_to_price=4.31,
            position_intent="sell_to_close", **kwargs,
        )

    def test_indicative_quote_does_not_replace_exit_prices(self):
        self.broker.get_latest_option_quote.return_value = quote(feed="indicative")
        result = self.sell()
        self.assertEqual("4.33", self.broker._post.call_args.args[1]["limit_price"])
        self.assertEqual(4.31, self.broker._wait_for_fill.call_args.kwargs["step_to_price"])
        self.assertEqual("4.35", result["filled_avg_price"])

    def test_unverified_or_invalid_quote_cannot_override_supplied_exit(self):
        cases = [
            {"bp": 4.38, "ap": 4.40}, quote(feed=None), quote(symbol="OTHER"),
            quote(t=None), quote(t="2026-09-04T12:00:00"),
            quote(t=(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat()),
            quote(t=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()),
            quote(bp=float("nan")), quote(ap=float("inf")), quote(bp=-1),
            quote(bp=4.5, ap=4.3), None,
        ]
        for candidate in cases:
            with self.subTest(quote=candidate):
                self.broker.get_latest_option_quote.return_value = candidate
                self.sell()
                self.assertEqual("4.33", self.broker._post.call_args.args[1]["limit_price"])

    def test_fresh_explicit_opra_can_requote_non_authoritative_order(self):
        self.sell()
        self.assertEqual("4.39", self.broker._post.call_args.args[1]["limit_price"])
        self.assertEqual(4.38, self.broker._wait_for_fill.call_args.kwargs["step_to_price"])

    def test_tradier_exit_preserves_bid_and_logs_sell_reference_not_ask(self):
        self.sell(price_authority="tradier", order_context={
            "quote_bid": 4.33, "quote_ask": 4.35, "quote_mid": 4.34,
        })
        self.broker.get_latest_option_quote.assert_not_called()
        self.assertEqual("4.33", self.broker._post.call_args.args[1]["limit_price"])
        references = [c.kwargs for c in self.flow.call_args_list
                      if c.kwargs.get("event_type") in {"authoritative_quote", "execution_summary"}]
        self.assertEqual(2, len(references))
        self.assertTrue(all(e["limit_price"] == 4.33 for e in references))

    def test_tradier_entry_keeps_approved_ceiling_without_alpaca_quote(self):
        self.broker.get_latest_option_quote.return_value = None
        self.broker.place_option_order(
            SYMBOL, 2, "buy", limit_price=4.16, max_acceptable_price=4.20,
            price_authority="tradier", position_intent="buy_to_open",
            order_context={"quote_bid": 4.14, "quote_ask": 4.16},
        )
        self.broker.get_latest_option_quote.assert_not_called()
        self.assertEqual("4.16", self.broker._post.call_args.args[1]["limit_price"])
        self.assertEqual(4.20, self.broker._wait_for_fill.call_args.kwargs["step_to_price"])
        self.assertFalse(self.broker._wait_for_fill.call_args.kwargs["allow_market_fallback"])

    def test_quote_exception_does_not_prevent_protective_exit(self):
        self.broker.get_latest_option_quote.side_effect = RuntimeError("unavailable")
        self.sell(allow_market_fallback=True)
        self.assertEqual("4.33", self.broker._post.call_args.args[1]["limit_price"])
        self.assertTrue(self.broker._wait_for_fill.call_args.kwargs["allow_market_fallback"])

    def test_live_tradier_entry_does_not_acquire_paper_ceiling_step(self):
        self.broker.base = "https://api.alpaca.markets"
        self.broker.place_option_order(
            SYMBOL, 2, "buy", limit_price=4.16, step_to_price=4.17,
            max_acceptable_price=4.20, price_authority="tradier",
            position_intent="buy_to_open", order_context={"quote_ask": 4.17},
        )
        self.broker.get_latest_option_quote.assert_not_called()
        self.assertEqual(4.17, self.broker._wait_for_fill.call_args.kwargs["step_to_price"])

    def test_invalid_quote_rejection_is_visible_without_faking_broker_requote(self):
        self.broker.get_latest_option_quote.return_value = quote(feed="indicative")
        self.sell()
        events = [c.kwargs for c in self.flow.call_args_list]
        self.assertFalse(any(e.get("event_type") == "broker_requote" for e in events))
        ignored = next(e for e in events if e.get("event_type") == "broker_quote_not_used")
        self.assertIn("modified_or_unknown_feed", ignored["message"])


class OptionQuoteFeedTests(unittest.TestCase):
    def test_entry_caller_passes_quote_clocks_to_durable_order_context(self):
        # Wiring test complements real recovery persistence test for closes.
        source = Path(__file__).parents[1] / "trading/entry/tick.py"
        calls = [n for n in ast.walk(ast.parse(source.read_text()))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "place_option_order"]
        self.assertEqual(1, len(calls))
        context = next(k.value for k in calls[0].keywords if k.arg == "order_context")
        keys = {k.value for k in context.keys if isinstance(k, ast.Constant)}
        self.assertTrue({"quote_received_at", "quote_bid_time_ms", "quote_ask_time_ms"} <= keys)

    def test_tradier_retains_exchange_times_and_adds_response_receive_time(self):
        broker = TradierChainMixin()
        broker.api_key = "offline-only"
        raw = {"bid": 4.33, "ask": 4.35, "bid_date": 1788541339000,
               "ask_date": 1788541339001}
        broker._get = Mock(return_value={"quotes": {"quote": raw}})
        before = datetime.now(timezone.utc)
        result = broker.get_option_quote(SYMBOL)
        after = datetime.now(timezone.utc)
        self.assertEqual(raw["bid_date"], result["bid_date"])
        self.assertEqual(raw["ask_date"], result["ask_date"])
        self.assertLessEqual(before, datetime.fromisoformat(result["quote_received_at"]))
        self.assertLessEqual(datetime.fromisoformat(result["quote_received_at"]), after)

    def test_requests_explicit_opra_and_preserves_contract_and_timestamp(self):
        broker = AlpacaBarsMixin()
        broker.data = "https://data.alpaca.markets"
        raw = {"bp": 4.38, "ap": 4.40, "t": "2026-09-04T17:02:19.73793695Z"}
        broker._get = Mock(return_value={"quotes": {SYMBOL: raw}})
        result = broker.get_latest_option_quote(SYMBOL)
        self.assertEqual({"symbols": SYMBOL, "feed": "opra"}, broker._get.call_args.kwargs["params"])
        self.assertEqual("opra", result["feed"])
        self.assertEqual(SYMBOL, result["symbol"])
        self.assertEqual(raw["t"], result["t"])
        self.assertNotIn("feed", raw)

    def test_unavailable_opra_has_no_indicative_fallback(self):
        broker = AlpacaBarsMixin()
        broker.data = "https://data.alpaca.markets"
        broker._get = Mock(side_effect=RuntimeError("OPRA unavailable"))
        with patch("broker.alpaca_bars.logger"):
            self.assertIsNone(broker.get_latest_option_quote(SYMBOL))
        self.assertEqual(1, broker._get.call_count)
        self.assertEqual("opra", broker._get.call_args.kwargs["params"].get("feed"))


if __name__ == "__main__":
    unittest.main()
