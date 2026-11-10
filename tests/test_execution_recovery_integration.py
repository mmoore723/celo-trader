"""Recovery isolation and integration with existing position-management callers."""
import unittest
import json
from unittest.mock import Mock, patch

from tests import test_execution_recovery as fixtures
from broker.recovery import reconcile_orders
from database.schema import _init_db_at


class RecoveryIntegrationTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp
    make_client = fixtures.RecoveryTests.make_client
    get = fixtures.RecoveryTests.get
    post = fixtures.RecoveryTests.post
    context = fixtures.RecoveryTests.context
    enter = fixtures.RecoveryTests.enter
    rows = fixtures.RecoveryTests.rows

    def test_daily_loss_after_full_fill_cleans_closed_state_before_reraising(self):
        from trading.position_manager.close import _close_position
        from risk import DailyLossLimitReached
        self.enter()
        trade = self.rows()[0]
        self.next_status, self.next_qty, self.next_price = 'filled', '3', '1.50'
        state = {'positions': {trade['id']: {'exit_pending_reason': 'test_exit'},
                               999: {'keep': True}}, 'account_balance': 4000,
                 'flip_eligible': True, 'flip_ticker': 'SPY', 'flip_direction': 'bearish'}
        risk = Mock()
        error = DailyLossLimitReached('post-fill loss')
        risk.record_pnl.side_effect = error
        persisted = {'open_positions': {str(trade['id']): {}, '999': {'keep': True}}}
        def update(path, mutate):
            persisted.update(mutate(persisted))
        with patch('trading.position_manager.close.get_user_state', return_value=state), \
             patch('trading.position_manager.close.get_user_risk', return_value=risk), \
             patch('trading.position_manager.close.get_user_trade_log', return_value=Mock()), \
             patch('trading.position_manager.close.set_user_trade_log'), \
             patch('config.atomic_update_json', side_effect=update), \
             patch('database.log_event'), patch('database.record_paper_option_quote'), \
             patch('database.link_broker_order_to_trade'), patch('ai_reasoning.narrator.narrate_exit'), \
             patch('database.insert_trade', side_effect=AssertionError('Duplicate insert')), \
             patch('database.close_trade', side_effect=AssertionError('Duplicate close')):
            with self.assertRaises(DailyLossLimitReached) as caught:
                _close_position(self.client, trade, 1.50, 'test_exit')
        self.assertIs(error, caught.exception)
        self.assertEqual('closed', self.rows()[0]['status'])
        self.assertNotIn(trade['id'], state['positions'])
        self.assertEqual({'keep': True}, state['positions'][999])
        self.assertNotIn(str(trade['id']), persisted['open_positions'])
        self.assertIn('999', persisted['open_positions'])
        self.assertFalse(state['flip_eligible'])
        self.assertEqual(2, len(self.submissions))
        risk.record_pnl.assert_called_once()

    def test_other_user_database_and_other_account_cannot_recover_our_order(self):
        self.next_status, self.next_qty = "pending_cancel", "1"
        self.enter()
        original = self.rows()
        other_path = self.path.parent / "other-user" / "trades_paper.db"
        other_path.parent.mkdir()
        _init_db_at(other_path)
        client = self.make_client()
        with patch("config.get_db_path", return_value=other_path):
            self.assertEqual(set(), reconcile_orders(client))
        client._get.assert_called_once()
        self.assertEqual(original, self.rows())
        self.settings["active_broker_account_id"] = "alpaca:paper:account-b"
        client = self.make_client()
        client._get = Mock(return_value={"id": "account-b"})
        self.assertEqual(set(), reconcile_orders(client))
        client._get.assert_called_once()
        self.assertEqual(original, self.rows())

    def test_position_close_caller_does_not_split_or_book_fill_twice(self):
        from trading.position_manager.close import _close_position
        self.enter()
        trade = self.rows()[0]
        self.next_status, self.next_qty, self.next_price = "canceled", "1", "1.50"
        state = {"positions": {}, "account_balance": 4000}
        with patch("trading.position_manager.close.get_user_state", return_value=state), \
             patch("database.log_event"), patch("database.record_paper_option_quote"), \
             patch("database.link_broker_order_to_trade"), patch("ai_reasoning.narrator.narrate_exit"), \
             patch("database.insert_trade", side_effect=AssertionError("Duplicate insert")), \
             patch("database.close_trade", side_effect=AssertionError("Duplicate close")):
            _close_position(self.client, trade, 1.50, "test_exit")
        self.assertEqual(2, len(self.rows()))
        self.assertEqual(2, next(t for t in self.rows() if t["status"] == "open")["contracts"])
        self.assertAlmostEqual(-10, sum(t["realized_pnl"] or 0 for t in self.rows()))

    def test_unpriced_close_restart_reconciles_original_order_before_retry(self):
        from trading.position_manager.close import _close_position
        self.enter()
        trade = self.rows()[0]
        self.next_status, self.next_qty, self.next_price = 'pending_cancel', '1', '1.50'
        state = {'positions': {}, 'account_balance': 4000}
        with patch('trading.position_manager.close.get_user_state', return_value=state), \
             patch('trading.position_manager.close._reconcile_if_phantom', return_value=False), \
             patch('database.log_event'), patch('database.record_paper_option_quote'), \
             patch('database.link_broker_order_to_trade'), patch('ai_reasoning.narrator.narrate_exit'), \
             patch('database.insert_trade', side_effect=AssertionError('Duplicate insert')), \
             patch('database.close_trade', side_effect=AssertionError('Duplicate close')):
            _close_position(self.client, trade, None, 'research_structural_stop', pricing_unavailable=True)
            self.assertEqual('market', self.submissions[-1]['type'])
            self.assertNotIn('limit_price', self.submissions[-1])
            remaining = next(t for t in self.rows() if t['status'] == 'open')
            self.assertEqual(2, remaining['contracts'])
            before = len(self.submissions)
            restarted = self.make_client()
            _close_position(restarted, remaining, None, 'research_structural_stop', pricing_unavailable=True)
            self.assertEqual(before, len(self.submissions))
            self.assertEqual(2, next(t for t in self.rows() if t['status'] == 'open')['contracts'])
            self.assertAlmostEqual(-10, sum(t['realized_pnl'] or 0 for t in self.rows()))

    def test_close_preserves_tradier_bid_and_durable_quote_timestamps(self):
        from trading.position_manager.close import _close_position
        self.enter()
        trade = self.rows()[0]
        self.next_status, self.next_qty, self.next_price = "canceled", "1", "1.50"
        self.client.get_latest_option_quote.reset_mock()
        self.client.get_latest_option_quote.return_value = {"bp": 2.0, "ap": 2.5}
        state = {"positions": {}, "account_balance": 4000}
        reference = {"bid": 1.48, "ask": 1.50, "mid": 1.49, "quote_source": "tradier",
                     "bid_date": 1788541339000, "ask_date": 1788541339001,
                     "quote_received_at": "2026-09-04T17:02:20+00:00"}
        with patch("trading.position_manager.close.get_user_state", return_value=state), \
             patch("database.log_event"), patch("database.record_paper_option_quote"), \
             patch("database.link_broker_order_to_trade"), patch("ai_reasoning.narrator.narrate_exit"), \
             patch("database.insert_trade", side_effect=AssertionError("Duplicate insert")), \
             patch("database.close_trade", side_effect=AssertionError("Duplicate close")):
            _close_position(self.client, trade, 1.48, "test_exit", reference_quote=reference)
        self.client.get_latest_option_quote.assert_not_called()
        self.assertEqual("1.48", self.submissions[-1]["limit_price"])
        records = [json.loads(row["body"]) for row in self.rows("execution_recovery")]
        context = next(row["context"] for row in records if row["side"] == "sell")
        self.assertEqual(reference["bid_date"], context["quote_bid_time_ms"])
        self.assertEqual(reference["ask_date"], context["quote_ask_time_ms"])
        self.assertEqual(reference["quote_received_at"], context["quote_received_at"])
        self.assertEqual(2, next(t for t in self.rows() if t["status"] == "open")["contracts"])
        self.assertAlmostEqual(-10, sum(t["realized_pnl"] or 0 for t in self.rows()))

    def test_stage1_restores_from_real_partial_exit_and_preserves_other_exit_latch(self):
        from database.execution_recovery import connect
        from trading.recovery_state import restore_stage1
        entry = self.enter()
        self.next_status, self.next_qty, self.next_price = "canceled", "1", "1.70"
        self.client.place_option_order(fixtures.SYMBOL, 1, "sell", limit_price=1.70,
            position_intent="sell_to_close", order_context={"trade_id": entry["accounted_trade_id"],
                "expected_contracts": 3, "exit_reason": "stage1_profit_take"})
        trade = next(t for t in self.rows() if t["status"] == "open")
        with patch("trading.recovery_state.get_conn", side_effect=lambda: connect(self.path)):
            ps = {"exit_pending_reason": "stage1_profit_take"}
            restore_stage1(trade, ps)
            self.assertTrue(ps["stage1_done"])
            self.assertNotIn("exit_pending_reason", ps)
            ps = {"exit_pending_reason": "structural_stop"}
            restore_stage1(trade, ps)
            self.assertEqual("structural_stop", ps["exit_pending_reason"])

    def test_network_post_timeout_is_one_request_not_transport_retry(self):
        from broker.alpaca_core import AlpacaCoreMixin
        from requests.exceptions import Timeout
        client = AlpacaCoreMixin.__new__(AlpacaCoreMixin)
        client.headers = {}
        with patch("broker.alpaca_core.requests.post", side_effect=Timeout("offline")) as post, \
             patch("broker.alpaca_core.log_event"):
            with self.assertRaises(Timeout):
                client._post("https://paper-api.alpaca.markets/v2/orders", {"client_order_id": "test"})
        self.assertEqual(1, post.call_count)

    def test_atr10_partial_recovery_finishes_exact_half_then_keeps_runner(self):
        from database.execution_recovery import connect
        from trading.research_order_exit import partial_remaining, ATR10
        from trading.recovery_state import restore_stage1
        context = self.context()
        context['entry_record']['strategy_id'] = ATR10
        context['entry_record']['strategy_context_json'] = json.dumps({
            'strategy_version': '0.1.0.research.2', 'research_order_route': 'exact_research_v1'})
        self.next_qty = '6'
        entry = self.client.place_option_order(fixtures.SYMBOL, 6, 'buy', limit_price=1.6,
                    position_intent='buy_to_open', order_context=context)
        parent = entry['accounted_trade_id']
        self.next_status, self.next_qty, self.next_price = 'canceled', '1', '2.08'
        self.client.place_option_order(fixtures.SYMBOL, 3, 'sell', limit_price=2.08,
            position_intent='sell_to_close', order_context={'trade_id': parent, 'expected_contracts': 6,
            'exit_reason': 'stage1_research_atr10_profit_take'})
        with patch('database.get_conn', side_effect=lambda: connect(self.path)):
            trade = next(row for row in self.rows() if row['status'] == 'open')
            self.assertEqual(5, trade['contracts'])
            self.assertEqual(2, partial_remaining(trade))
            state = {'exit_pending_reason': 'stage1_research_atr10'}
            restore_stage1(trade, state)
            self.assertFalse(state['stage1_done'])
            restarted = self.make_client()
            reconcile_orders(restarted)
            self.next_status, self.next_qty = 'filled', '2'
            restarted.place_option_order(fixtures.SYMBOL, 2, 'sell', limit_price=2.08,
                position_intent='sell_to_close', order_context={'trade_id': parent, 'expected_contracts': 5,
                'exit_reason': 'stage1_research_atr10_profit_take'})
            trade = next(row for row in self.rows() if row['status'] == 'open')
            self.assertEqual(3, trade['contracts'])
            self.assertEqual(0, partial_remaining(trade))
            restore_stage1(trade, state)
            self.assertTrue(state['stage1_done'])
            self.assertNotIn('exit_pending_reason', state)
            before = self.rows()
            reconcile_orders(self.make_client())
            self.assertEqual(before, self.rows())

    def test_partial_exit_database_failure_keeps_parent_and_pnl_unchanged(self):
        self.enter()
        trade = self.rows()[0]
        self.next_status, self.next_qty, self.next_price = "canceled", "1", "1.50"
        with patch("database.execution_fills.save", side_effect=RuntimeError("disk full")):
            self.assertIsNone(self.client.place_option_order(fixtures.SYMBOL, 1, "sell", limit_price=1.50,
                position_intent="sell_to_close", order_context={"trade_id": trade["id"],
                    "expected_contracts": 3, "exit_reason": "test_exit"}))
        self.assertEqual([trade], self.rows())
        self.assertEqual([], self.rows("daily_summary"))
        reconcile_orders(self.make_client())
        self.assertEqual(2, next(t for t in self.rows() if t["status"] == "open")["contracts"])
        self.assertAlmostEqual(-10, self.rows("daily_summary")[0]["total_pnl"])


if __name__ == "__main__":
    unittest.main()
