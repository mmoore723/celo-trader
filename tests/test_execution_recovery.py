"""Offline fault injection against the actual durable Alpaca placement path."""
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from broker.alpaca_client import AlpacaClient
from broker.recovery import reconcile_orders, scope
from database.schema import _init_db_at

SYMBOL = "SPY260911C00770000"
ACCOUNT = "alpaca:paper:offline-account"
FILL_TIME = "2026-09-03T18:00:00Z"


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "trades_paper.db"
        _init_db_at(self.path)
        self.settings = {"paper_trading": True, "active_broker_account_id": ACCOUNT}
        self.stack.enter_context(patch("config.get_settings", return_value=self.settings))
        self.stack.enter_context(patch("config.get_db_path", return_value=self.path))
        self.stack.enter_context(patch("trading.position_manager.close._now_et",
                                       return_value=datetime.fromisoformat('2026-09-03T14:00:00-04:00')))
        for name in ("broker.alpaca_orders.time.sleep", "broker.alpaca_orders._record_flow",
                     "broker.alpaca_orders.log_event", "broker.common._debounced_log"):
            self.stack.enter_context(patch(name))
        self.orders, self.submissions = {}, []
        self.next_status, self.next_qty, self.next_price = "filled", "3", "1.60"
        self.client = self.make_client()

    def make_client(self):
        client = object.__new__(AlpacaClient)
        client.base, client.api_key = "https://paper-api.alpaca.markets", "offline-key"
        client.get_latest_option_quote = Mock(return_value=None)
        client.cancel_order = Mock(return_value=True)
        client._patch = Mock(side_effect=RuntimeError("No price step in this fixture"))
        client._get = Mock(side_effect=self.get)
        client._post = Mock(side_effect=self.post)
        return client

    def get(self, url, params=None):
        if url.endswith('/clock'):
            return {'timestamp': '2026-09-03T14:00:00-04:00', 'is_open': True,
                    'next_close': '2026-09-03T16:00:00-04:00'}
        if url.endswith("/account"):
            return {"id": "offline-account"}
        if url.endswith("orders:by_client_order_id"):
            return copy.deepcopy(next(o for o in self.orders.values()
                                      if o["client_order_id"] == params["client_order_id"]))
        return copy.deepcopy(self.orders[url.rsplit("/", 1)[-1]])

    def post(self, url, payload):
        self.submissions.append(dict(payload))
        oid = f"order-{len(self.submissions)}"
        self.orders[oid] = {**payload, "id": oid, "status": self.next_status,
                            "filled_qty": self.next_qty, "filled_avg_price": self.next_price,
                            "filled_at": FILL_TIME}
        return copy.deepcopy(self.orders[oid])

    def context(self):
        strategy_context = json.dumps({
            "strategy_id": "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
            "previous_high": 771.25,
            "direction": "bullish",
        }, sort_keys=True)
        return {"intent_id": "offline-intent", "stop_factor": 0.80, "target_factor": 1.50,
                "direction": "bullish", "confidence": 0.8,
                "entry_record": {"ticker": "SPY", "contract_symbol": SYMBOL,
                    "option_type": "call", "strike": 770, "expiry": "2026-09-11",
                    "paper": 1, "strategy_id": "V2_SPY_TREND_CONT", "tier": "main",
                    "broker_account_id": ACCOUNT, "entry_reason": "offline replay",
                    "strategy_context_json": strategy_context}}

    def enter(self, context=None):
        return self.client.place_option_order(SYMBOL, 3, "buy", limit_price=1.60,
            position_intent="buy_to_open", max_wait_seconds=5,
            order_context=context or self.context())

    def rows(self, table="trades"):
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]

    def test_invalid_limit_creates_no_order_or_recovery_record(self):
        for price in (None, 0, -1, float('nan'), float('inf')):
            with self.subTest(price=price):
                result = self.client.place_option_order(SYMBOL, 3, "buy", limit_price=price,
                    position_intent="buy_to_open", order_context=self.context())
                self.assertIsNone(result)
        self.assertEqual([], self.submissions)
        self.assertEqual([], self.rows('execution_recovery'))

    def test_normal_entry_is_booked_once_and_duplicate_intent_never_posts(self):
        fill = self.enter()
        self.assertEqual(3, fill["filled_qty"])
        self.assertEqual(1, len(self.rows()))
        self.assertAlmostEqual(1.60, self.rows()[0]["entry_price"])
        self.assertEqual(
            771.25,
            json.loads(self.rows()[0]["strategy_context_json"])["previous_high"],
        )
        self.assertIsNone(self.enter())
        self.assertEqual(1, len(self.submissions))
        self.assertEqual(set(), reconcile_orders(self.make_client()))

    def test_partial_entry_survives_unconfirmed_cancel_then_restart(self):
        self.next_status, self.next_qty = "pending_cancel", "1"
        fill = self.enter()
        self.assertEqual(1, fill["filled_qty"])
        self.assertTrue(fill["recovery_pending"])
        self.assertEqual(1, self.rows()[0]["contracts"])
        self.assertIsNone(self.enter({**self.context(), "intent_id": "different-intent"}))
        self.assertEqual(1, len(self.submissions))
        self.orders["order-1"].update(status="filled", filled_qty="3", filled_avg_price="1.70")
        self.assertEqual(set(), reconcile_orders(self.make_client()))
        self.assertEqual(3, self.rows()[0]["contracts"])
        self.assertAlmostEqual(1.70, self.rows()[0]["entry_price"])
        reconcile_orders(self.make_client())
        self.assertEqual(1, len(self.rows()))

    def test_restart_between_submit_and_response_recovers_by_client_id(self):
        def die(url, payload):
            self.post(url, payload)
            raise SystemExit("simulated process death")
        self.client._post.side_effect = die
        with self.assertRaises(SystemExit):
            self.enter()
        self.assertEqual([], self.rows())
        self.assertEqual(set(), reconcile_orders(self.make_client()))
        self.assertEqual(3, self.rows()[0]["contracts"])
        self.assertEqual(1, len(self.submissions))

    def test_unknown_submission_does_not_retry_or_invent_a_fill(self):
        from requests.exceptions import Timeout
        self.client._post.side_effect = Timeout("offline")
        self.assertIsNone(self.enter())
        self.assertEqual([], self.rows())
        self.assertIsNone(self.enter())
        self.assertEqual(1, self.client._post.call_count)
        self.assertIsNone(self.client.last_rejection_reason)

    def test_missing_price_is_retained_for_recovery_not_filled_at_limit(self):
        self.next_price = None
        self.assertIsNone(self.enter())
        self.assertEqual([], self.rows())
        self.orders["order-1"]["filled_avg_price"] = "1.57"
        reconcile_orders(self.make_client())
        self.assertAlmostEqual(1.57, self.rows()[0]["entry_price"])

    def test_partial_exit_late_fill_and_replay_preserve_exact_quantity_and_pnl(self):
        entry = self.enter()
        self.next_status, self.next_qty, self.next_price = "pending_cancel", "1", "1.50"
        fill = self.client.place_option_order(SYMBOL, 2, "sell", limit_price=1.50,
            position_intent="sell_to_close", max_wait_seconds=5,
            order_context={"trade_id": entry["accounted_trade_id"], "expected_contracts": 3,
                           "exit_reason": "stage1_profit_take"})
        self.assertEqual(1, fill["filled_qty"])
        self.assertAlmostEqual(-10, fill["accounted_pnl"])
        first_closed = next(row for row in self.rows() if row["status"] == "closed")
        self.orders["order-2"].update(status="filled", filled_qty="2", filled_avg_price="1.40")
        reconcile_orders(self.make_client())
        reconcile_orders(self.make_client())
        rows = self.rows()
        self.assertEqual(1, next(row for row in rows if row["status"] == "open")["contracts"])
        self.assertEqual(first_closed, next(row for row in rows if row["id"] == first_closed["id"]))
        self.assertAlmostEqual(-40, sum(row["realized_pnl"] or 0 for row in rows))
        self.assertAlmostEqual(-40, self.rows("daily_summary")[0]["total_pnl"])
        self.assertEqual(2, len(self.submissions))

    def test_scope_and_concurrent_request_fail_closed_without_post(self):
        store = scope(self.client)
        with store.lock(SYMBOL) as held:
            self.assertTrue(held)
            self.assertIsNone(self.enter())
        self.assertEqual([], self.submissions)
        self.settings["active_broker_account_id"] = "alpaca:paper:other-account"
        self.client = self.make_client()
        self.assertIsNone(self.enter())
        self.assertEqual([], self.submissions)

    def test_zero_fill_terminal_order_does_not_create_trade(self):
        self.next_status, self.next_qty, self.next_price = "canceled", "0", None
        self.assertIsNone(self.enter())
        self.assertEqual([], self.rows())
        record = json.loads(self.rows("execution_recovery")[0]["body"])
        self.assertFalse(record["active"])


if __name__ == "__main__":
    unittest.main()
