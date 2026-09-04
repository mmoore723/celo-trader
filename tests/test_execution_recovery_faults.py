"""Transaction, replacement, fallback, scope and caller integration fault cases."""
import copy
import unittest
from unittest.mock import Mock, patch

from tests import test_execution_recovery as fixtures
from broker.recovery import reconcile_orders, scope
from database.execution_fills import apply_fills


class RecoveryFaultTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp
    make_client = fixtures.RecoveryTests.make_client
    get = fixtures.RecoveryTests.get
    post = fixtures.RecoveryTests.post
    context = fixtures.RecoveryTests.context
    enter = fixtures.RecoveryTests.enter
    rows = fixtures.RecoveryTests.rows

    def sell(self, entry, *, emergency=False):
        return self.client.place_option_order(fixtures.SYMBOL, 3, "sell", limit_price=1.50,
            position_intent="sell_to_close", max_wait_seconds=5, allow_market_fallback=emergency,
            order_context={"trade_id": entry["accounted_trade_id"], "expected_contracts": 3,
                           "exit_reason": "panic" if emergency else "test_exit"})

    def test_journal_and_cursor_rollback_together_then_recover_once(self):
        with patch("database.execution_fills.save", side_effect=RuntimeError("disk full")):
            self.assertIsNone(self.enter())
        self.assertEqual([], self.rows())
        self.assertEqual([], self.rows("signal_journal"))
        reconcile_orders(self.make_client())
        reconcile_orders(self.make_client())
        self.assertEqual(1, len(self.rows()))
        self.assertEqual(1, len(self.rows("signal_journal")))
        self.assertEqual(1, len(self.submissions))

    def test_crash_after_accounting_commit_never_rebooks_or_resubmits(self):
        def commit_then_die(store, record):
            apply_fills(store, record)
            raise SystemExit("lost caller response")
        with patch("broker.recovery.apply_fills", side_effect=commit_then_die):
            with self.assertRaises(SystemExit):
                self.enter()
        reconcile_orders(self.make_client())
        self.assertIsNone(self.enter())
        self.assertEqual(1, len(self.rows()))
        self.assertEqual(1, len(self.submissions))

    def test_durable_write_failure_prevents_broker_post(self):
        with patch("database.execution_recovery.RecoveryStore.put", side_effect=RuntimeError("disk full")):
            self.assertIsNone(self.enter())
        self.assertEqual([], self.submissions)

    def test_partial_emergency_fallback_is_not_lost_and_late_fill_is_incremental(self):
        entry = self.enter()
        self.next_status, self.next_qty, self.next_price = "partially_filled", "1", "1.50"
        def cancel(oid):
            self.orders[oid]["status"] = "canceled"
            self.next_price = "1.20"
            return True
        self.client.cancel_order.side_effect = cancel
        fill = self.sell(entry, emergency=True)
        self.assertEqual(2, fill["filled_qty"])
        self.assertAlmostEqual(1.35, fill["confirmed_fill_price"])
        self.assertEqual("2", self.submissions[-1]["qty"])
        self.orders["order-3"].update(status="filled", filled_qty="2", filled_avg_price="1.10")
        reconcile_orders(self.make_client())
        self.assertTrue(all(t["status"] == "closed" for t in self.rows()))
        self.assertAlmostEqual(-110, sum(t["realized_pnl"] for t in self.rows()))
        self.assertEqual(3, len(self.submissions))

    def test_response_lost_during_market_fallback_recovers_exact_remainder(self):
        entry = self.enter()
        self.next_status, self.next_qty, self.next_price = "partially_filled", "1", "1.50"
        self.client.cancel_order.side_effect = lambda oid: self.orders[oid].update(status="canceled") or True
        def post(url, payload):
            if payload["type"] == "market":
                self.next_status, self.next_qty, self.next_price = "filled", "2", "1.10"
                self.post(url, payload)
                raise TimeoutError("accepted, response lost")
            return self.post(url, payload)
        self.client._post.side_effect = post
        fill = self.sell(entry, emergency=True)
        self.assertEqual(1, fill["filled_qty"])
        self.assertEqual("2", self.submissions[-1]["qty"])
        reconcile_orders(self.make_client())
        self.assertAlmostEqual(-110, sum(t["realized_pnl"] for t in self.rows()))
        self.assertEqual(3, len(self.submissions))

    def test_lost_patch_response_follows_child_and_counts_execution_ids_once(self):
        self.next_status, self.next_qty, self.next_price = "new", "0", None
        def replace(url, payload):
            parent = self.orders["order-1"]
            parent.update(status="replaced", filled_qty="1", filled_avg_price="1.50", replaced_by="child")
            self.orders["child"] = {**parent, "id": "child", "status": "filled", "replaced_by": None,
                                     "replaces": "order-1", "filled_qty": "3", "filled_avg_price": "1.70"}
            raise TimeoutError("replacement accepted, response lost")
        self.client._patch.side_effect = replace
        activity = lambda oid, qty, price, cumulative: {
            "id": f"fill::{oid}", "order_id": oid, "symbol": fixtures.SYMBOL, "side": "buy",
            "qty": str(qty), "price": str(price), "cum_qty": str(cumulative),
            "transaction_time": fixtures.FILL_TIME,
        }
        def get(url, params=None):
            if url.endswith("/activities/FILL"):
                return [activity("order-1", 1, 1.50, 1)] if params["order_id"] == "order-1" else [activity("child", 2, 1.80, 3)]
            return self.get(url, params)
        self.client._get.side_effect = get
        fill = self.client.place_option_order(fixtures.SYMBOL, 3, "buy", limit_price=1.50,
            step_to_price=1.80, position_intent="buy_to_open", max_wait_seconds=5, order_context=self.context())
        self.assertEqual(3, fill["filled_qty"])
        self.assertAlmostEqual(1.70, fill["confirmed_fill_price"])
        self.assertEqual(1, len(self.submissions))
        self.assertEqual(3, self.rows()[0]["contracts"])
        self.assertEqual(set(), reconcile_orders(self.make_client()))

    def test_legacy_key_alias_is_verified_without_changing_journal_identity(self):
        from broker.account_identity import fallback_account_identity
        alias = fallback_account_identity(self.client.api_key, True)
        self.settings["active_broker_account_id"] = alias
        context = self.context()
        context["entry_record"]["broker_account_id"] = alias
        self.enter(context)
        self.assertEqual(alias, self.rows()[0]["broker_account_id"])
        self.assertEqual(fixtures.ACCOUNT, self.rows("execution_recovery")[0]["account"])

    def test_stale_exit_quantity_and_wrong_mode_never_send_order(self):
        entry = self.enter()
        with patch("database.execution_fills._exit", side_effect=RuntimeError("crash")):
            self.next_status, self.next_qty = "filled", "3"
            self.assertIsNone(self.sell(entry))
        reconcile_orders(self.make_client())
        self.assertIsNone(self.sell(entry))
        self.assertEqual(2, len(self.submissions))
        self.settings["paper_trading"] = False
        self.assertIsNone(self.enter())
        self.assertEqual(2, len(self.submissions))

    def test_failed_position_snapshot_cannot_claim_account_is_flat(self):
        from broker.alpaca_positions import AlpacaPositionsMixin
        client = AlpacaPositionsMixin()
        client.base = self.client.base
        client._get = Mock(side_effect=TimeoutError("offline"))
        with self.assertRaises(TimeoutError):
            client.get_positions()
        with self.assertRaises(TimeoutError):
            client.get_open_orders()


if __name__ == "__main__":
    unittest.main()
