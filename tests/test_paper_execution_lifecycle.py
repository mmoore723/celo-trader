"""Offline broker-response replays; never submit orders to a real account."""
from contextlib import ExitStack
from datetime import date, datetime, timedelta
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from broker.alpaca_orders import AlpacaOrdersMixin
from database.schema import _init_db_at
from database.trades import close_trade, insert_trade
from trading.entry.contract import select_v2_orb_paper_contract
from trading.entry.tick import _entry_quote_is_fresh


class PaperExecutionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, kwargs in [
            ("config.get_settings", {"return_value": {"paper_trading": True}}),
            ("broker.alpaca_orders.time.sleep", {}),
            ("broker.alpaca_orders._record_flow", {}),
            ("broker.alpaca_orders.log_event", {}),
        ]:
            mock = self.stack.enter_context(patch(target, **kwargs))
            if target.endswith("_record_flow"):
                self.events = mock
            if target.endswith("log_event"):
                self.logs = mock

    def broker(self, responses):
        broker = AlpacaOrdersMixin()
        broker.api_key = "offline-test-only"
        broker.base = "https://paper-api.alpaca.markets"
        broker._get = Mock(side_effect=responses)
        broker._post = Mock(return_value={"id": "entry-1", "status": "new"})
        broker._patch = Mock(return_value={"id": "entry-1", "status": "new"})
        broker.cancel_order = Mock(return_value=True)
        broker.get_latest_option_quote = Mock(return_value={"bp": 1.50, "ap": 1.60})
        return broker

    def wait(self, broker, *, qty=3, side="buy", emergency=False):
        return broker._wait_for_fill(
            "entry-1", max_wait=5, limit_price=1.60, qty=qty, side=side,
            symbol="SPY260911C00770000",
            position_intent="buy_to_open" if side == "buy" else "sell_to_close",
            allow_market_fallback=emergency,
        )

    def test_delayed_or_unknown_quote_cannot_pass_entry_freshness_gate(self):
        for age in [901, 911.7, 1023.4, None, -1, float("nan"), float("inf"), "invalid"]:
            with self.subTest(age=age):
                self.assertFalse(_entry_quote_is_fresh({"quote_age_seconds": age}))
        self.assertTrue(_entry_quote_is_fresh({"quote_age_seconds": 1.2}))

    def test_partial_entry_keeps_only_actual_fill_and_does_not_chase(self):
        broker = self.broker([
            *[{"status": "partially_filled", "filled_qty": "1", "filled_avg_price": "1.57"}] * 5,
            {"status": "canceled", "filled_qty": "1", "filled_avg_price": "1.57"},
        ])
        result = self.wait(broker)
        self.assertEqual(1, result["filled_qty"])
        self.assertAlmostEqual(1.57, result["confirmed_fill_price"])
        self.assertTrue(result["partial_fill"])
        broker._post.assert_not_called()
        messages = " ".join(call.args[2] for call in self.logs.call_args_list)
        self.assertNotIn("re-submitting as market", messages)
        self.assertNotIn("ordering the remainder at market", messages)

    def test_routine_partial_exit_preserves_actual_quantity(self):
        broker = self.broker([
            {"status": "canceled", "filled_qty": "1", "filled_avg_price": "1.74"},
        ])
        result = self.wait(broker, side="sell")
        self.assertEqual(1, result["filled_qty"])
        self.assertTrue(result["partial_fill"])
        self.assertAlmostEqual(1.74, result["confirmed_fill_price"])
        broker._post.assert_not_called()

    def test_fill_during_cancel_is_not_followed_by_duplicate_order(self):
        broker = self.broker([
            *[{"status": "new", "filled_qty": "0"}] * 5,
            {"status": "filled", "filled_qty": "3", "filled_avg_price": "1.58"},
        ])
        result = self.wait(broker)
        self.assertEqual(3, result["filled_qty"])
        self.assertFalse(result["partial_fill"])
        broker._post.assert_not_called()

    def test_emergency_exit_fallback_only_sells_remaining_quantity(self):
        broker = self.broker([
            *[{"status": "partially_filled", "filled_qty": "1", "filled_avg_price": "1.50"}] * 5,
            {"status": "canceled", "filled_qty": "1", "filled_avg_price": "1.50"},
            {"status": "filled", "filled_qty": "2", "filled_avg_price": "1.20"},
        ])
        result = self.wait(broker, side="sell", emergency=True)
        payload = broker._post.call_args.args[1]
        self.assertEqual("2", payload["qty"])
        self.assertEqual("sell_to_close", payload["position_intent"])
        self.assertEqual(3, result["filled_qty"])
        self.assertAlmostEqual(1.30, result["confirmed_fill_price"])

    def test_unconfirmed_cancel_never_submits_emergency_replacement(self):
        broker = self.broker([{"status": "pending_cancel", "filled_qty": "0"}] * 10)
        self.assertIsNone(self.wait(broker, side="sell", emergency=True))
        broker._post.assert_not_called()
        self.assertTrue(any(c.kwargs.get("event_type") == "fallback_blocked_cancel_unconfirmed"
                            for c in self.events.call_args_list))

    def test_selected_contract_partial_entry_exit_and_pnl_use_broker_fills(self):
        expiry = (date.today() + timedelta(days=7)).isoformat()
        market = Mock()
        market.get_expirations.return_value = [expiry]
        market.get_option_chain.return_value = [
            {"symbol": "SPY260911C00770000", "strike": 770, "bid": 1.50, "ask": 1.60},
        ]
        contract, selection = select_v2_orb_paper_contract(market, "SPY", "bullish", 769, 1000)
        self.assertEqual("selected", selection["reason"])
        broker = self.broker([
            {"id": "entry-1", "status": "canceled", "filled_qty": "1", "filled_avg_price": "1.57"},
            {"id": "exit-1", "status": "filled", "filled_qty": "1", "filled_avg_price": "1.74"},
        ])
        entry = broker.place_option_order(
            contract["symbol"], 3, "buy", limit_price=1.60, max_acceptable_price=1.60,
            position_intent="buy_to_open", price_authority="tradier",
            order_context={"intent_id": "intent-1", "candidate_id": "candidate-1", "quote_bid": 1.50, "quote_ask": 1.60},
        )
        summary = [c.kwargs for c in self.events.call_args_list if c.kwargs.get("event_type") == "execution_summary"][-1]
        self.assertEqual("partially_filled", summary["status"])
        self.assertEqual(1, summary["filled_qty"])
        broker._post.return_value = {"id": "exit-1", "status": "new"}
        broker.get_latest_option_quote.return_value = {"bp": 1.73, "ap": 1.77}
        exit_fill = broker.place_option_order(
            contract["symbol"], entry["filled_qty"], "sell", limit_price=1.80,
            position_intent="sell_to_close",
        )
        self.assertEqual("1", broker._post.call_args.args[1]["qty"])
        self.assertEqual("sell_to_close", broker._post.call_args.args[1]["position_intent"])
        self.assertEqual("1.75", broker._post.call_args.args[1]["limit_price"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades_paper.db"
            _init_db_at(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            now = datetime.fromisoformat("2026-09-03T14:45:00-04:00")
            with patch("database.trades.get_conn", return_value=conn), patch(
                "database.trades._upsert_daily_summary"
            ), patch("database.option_quotes.record_paper_option_quote"), patch("config.save_settings"):
                trade_id = insert_trade(
                    "SPY", contract["symbol"], "call", 770, expiry,
                    entry["filled_qty"], entry["confirmed_fill_price"], now, "offline replay",
                    paper=True, candidate_id="candidate-1", entry_order_id=entry["id"], entry_fill_time=now,
                )
                pnl = close_trade(
                    trade_id, 1.80, now, "offline replay exit", paper=True,
                    confirmed_fill_price=exit_fill["confirmed_fill_price"],
                    exit_order_id=exit_fill["id"], exit_fill_time=now,
                )
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            conn.close()
        self.assertEqual(1, row["contracts"])
        self.assertAlmostEqual(1.57, row["entry_price"])
        self.assertAlmostEqual(1.74, row["exit_price"])
        self.assertAlmostEqual(17, pnl)  # Gross paper P&L, not a live net-profit claim.
        self.assertEqual("entry-1", row["entry_order_id"])
        self.assertEqual("exit-1", row["exit_order_id"])
        self.assertEqual("candidate-1", row["candidate_id"])


if __name__ == "__main__":
    unittest.main()
