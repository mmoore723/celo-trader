"""Offline integration: real loss guard, durable halt, close and fill recovery.

Only broker transport, market quotes, account state and auxiliary notifications
are replaced. The journal and recovery store are real temporary SQLite files.
This proves software behavior, not market liquidity or live broker execution.
"""
import copy
from unittest.mock import Mock, patch
import unittest

from tests import test_execution_recovery as fixtures
from risk import kill_lock
from risk.manager import RiskManager
from trading.loop.daily_loss import run_guarded_execution


class DailyLossRecoveryLifecycleTests(unittest.TestCase):
    make_client = fixtures.RecoveryTests.make_client
    get = fixtures.RecoveryTests.get
    post = fixtures.RecoveryTests.post
    context = fixtures.RecoveryTests.context
    rows = fixtures.RecoveryTests.rows

    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        self.settings.update(daily_loss_hard_cap_pct=10, max_daily_loss_pct=.1,
                             kill_lock_hours=24, broker_provider="alpaca")
        self.state = dict(day_start_balance=5000, account_balance=4400, positions={})
        self.risk = RiskManager(5000)
        for name in ("risk.guard.get_settings", "risk.kill_lock.get_settings"):
            self.stack.enter_context(patch(name, return_value=self.settings))
        self.stack.enter_context(patch("risk.kill_lock.get_user_data_dir", return_value=self.path.parent))
        self.stack.enter_context(patch("risk.kill_lock._KILL_LOCK_PATH", self.path.parent / "legacy.json"))
        self.stack.enter_context(patch("database.connection.get_db_path", return_value=self.path))
        for name in ("trading.state.get_user_state", "trading.controls.panic.get_user_state",
                     "trading.position_manager.close.get_user_state"):
            self.stack.enter_context(patch(name, side_effect=lambda *a, **k: self.state))
        self.stack.enter_context(patch("trading.position_manager.close.get_user_risk", side_effect=lambda: self.risk))
        self.stack.enter_context(patch("trading.position_manager.close.get_user_trade_log", return_value=Mock()))
        self.stack.enter_context(patch("trading.position_manager.close.get_bot_state_path", return_value=self.path.parent / "bot.json"))
        self.stack.enter_context(patch("trading.position_manager.close._snapshot_exit_annotations", return_value=None))
        self.stack.enter_context(patch("risk.guard.get_todays_realized_pnl", side_effect=lambda: sum(
            r["realized_pnl"] or 0 for r in self.rows())))
        for name in ("risk.guard.log_event", "database.log_event", "alerts.send_alert",
                     "ai_reasoning.narrator.narrate_exit", "database.record_paper_option_quote",
                     "database.link_broker_order_to_trade", "trading.controls.panic._refresh_session_pnl"):
            self.stack.enter_context(patch(name))
        self.market = Mock()
        self.market.get_option_quote.return_value = dict(bid=1.10, ask=1.20, mid=1.15,
                                                        quote_source="offline")
        self.clock = 100.0
        self.stack.enter_context(patch("trading.controls.panic.time.monotonic", side_effect=lambda: self.clock))
        # No hidden transport is permitted even if a future implementation
        # stops using the fixture's injected _get/_post methods.
        self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
        self.attach_snapshots(self.client)

    def attach_snapshots(self, client):
        def positions():
            totals = {}
            for row in self.orders.values():
                symbol = row["symbol"]
                totals[symbol] = totals.get(symbol, 0) + float(row["filled_qty"]) * (1 if row["side"] == "buy" else -1)
            return [{"symbol": symbol, "qty": str(qty)} for symbol, qty in totals.items() if qty]
        client.get_positions = Mock(side_effect=positions)
        client.get_open_orders = Mock(side_effect=lambda: [copy.deepcopy(r) for r in self.orders.values()
            if r["status"] not in {"filled", "canceled", "rejected", "expired"}])
        client.close_all_positions = Mock(side_effect=AssertionError("Tracked position must use accounted close"))

    def enter(self, context=None):
        context = context or self.context()
        return self.client.place_option_order(context["entry_record"]["contract_symbol"], 3, "buy",
            limit_price=1.60, position_intent="buy_to_open", max_wait_seconds=5, order_context=context)

    def strategy_context(self, strategy, ticker):
        context = self.context()
        context["intent_id"] = "offline-" + ticker
        context["entry_record"].update(strategy_id=strategy, ticker=ticker,
            contract_symbol=ticker + "260911C00770000", strategy_context_json="{}")
        return context

    def guarded_tick(self, *, balance=4400, valid=True):
        execute = Mock(side_effect=AssertionError("Entries must remain blocked"))
        run_guarded_execution(risk=self.risk, balance=balance, balance_valid=valid,
            collection_only=False, broker=self.client, market=self.market,
            user_id="offline", execute=execute)
        execute.assert_not_called()

    def restart(self):
        # Clear all retry state and reconstruct risk/client while preserving
        # only the on-disk halt, journal and fake broker's independent orders.
        self.state = dict(day_start_balance=5000, account_balance=4400, positions={})
        self.risk = RiskManager(5000)
        self.client = self.make_client()
        self.attach_snapshots(self.client)
        self.clock += 31

    def assert_flat_locked_once(self, count=2, quantity=3, pnl=-150):
        self.assertTrue(all(r["status"] == "closed" for r in self.rows()))
        self.assertEqual(quantity, sum(r["contracts"] for r in self.rows()))
        self.assertAlmostEqual(pnl, sum(r["realized_pnl"] for r in self.rows()))
        self.assertAlmostEqual(pnl, self.rows("daily_summary")[0]["total_pnl"])
        self.assertFalse(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])
        self.assertEqual(count, len(self.submissions))
        self.assertEqual([], self.client.get_positions())
        self.assertEqual([], self.client.get_open_orders())
        self.guarded_tick(balance=5000)
        self.assertEqual(count, len(self.submissions))

    def partial_then_restart(self, strategy, ticker="SPY"):
        context = self.strategy_context(strategy, ticker)
        self.enter(context)
        self.next_status, self.next_qty, self.next_price = "pending_cancel", "1", "1.10"
        self.guarded_tick()
        self.assertTrue(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])
        self.assertEqual(2, next(r for r in self.rows() if r["status"] == "open")["contracts"])
        self.assertAlmostEqual(-50, sum(r["realized_pnl"] or 0 for r in self.rows()))
        self.assertEqual(2, len(self.submissions))
        self.guarded_tick()  # retry throttle must not send another close
        self.assertEqual(2, len(self.submissions))
        self.orders["order-2"].update(status="filled", filled_qty="3", filled_avg_price="1.10")
        self.restart()
        self.guarded_tick(valid=False)  # stale equity cannot block reconciliation
        self.assert_flat_locked_once()
        self.assertEqual({strategy}, {r["strategy_id"] for r in self.rows()})

    def test_spy_trend_partial_exit_restart(self):
        self.partial_then_restart("V2_SPY_TREND_CONT")

    def test_failed_range_partial_exit_restart(self):
        self.partial_then_restart("V2_FAILED_OR_BREAK_VWAP_REVERSION")

    def test_afternoon_fvg_partial_exit_restart(self):
        self.partial_then_restart("V2_SPY_AFTERNOON_FVG")

    def test_orb_partial_exit_restart(self):
        self.partial_then_restart("V2_ORB_PULLBACK", "TSLA")

    def test_two_leg_partial_exit_restart(self):
        self.partial_then_restart("V2_TSLA_TWO_LEG_TREND_PULLBACK", "TSLA")

    def test_displacement_partial_exit_restart(self):
        self.partial_then_restart("CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG", "AMZN")

    def test_three_positions_one_pending_exit_does_not_block_other_closes(self):
        for strategy, ticker in (("V2_SPY_TREND_CONT", "SPY"),
                                 ("V2_TSLA_TWO_LEG_TREND_PULLBACK", "TSLA"),
                                 ("CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG", "AMZN")):
            self.enter(self.strategy_context(strategy, ticker))
        def partial_one(url, payload):
            partial = payload["symbol"].startswith("TSLA")
            self.next_status = "pending_cancel" if partial else "filled"
            self.next_qty, self.next_price = ("1" if partial else "3"), "1.10"
            return self.post(url, payload)
        self.client._post.side_effect = partial_one
        self.guarded_tick()
        open_rows = [r for r in self.rows() if r["status"] == "open"]
        self.assertEqual(1, len(open_rows))
        self.assertEqual(("TSLA", 2), (open_rows[0]["ticker"], open_rows[0]["contracts"]))
        self.assertEqual(6, len(self.submissions))
        self.assertTrue(kill_lock.flatten_pending())
        pending = next(r for r in self.orders.values() if r["side"] == "sell" and r["symbol"].startswith("TSLA"))
        pending.update(status="filled", filled_qty="3", filled_avg_price="1.10")
        self.restart()
        self.guarded_tick(valid=False)
        self.assert_flat_locked_once(count=6, quantity=9, pnl=-450)

    def seed_three_positions(self):
        for ticker in ("SPY", "TSLA", "AMZN"):
            self.enter(self.strategy_context("V2_SPY_TREND_CONT", ticker))

    def test_configured_three_position_limit_is_not_reported_as_two(self):
        from database import get_open_trades
        self.settings["max_concurrent_positions"] = 3
        self.seed_three_positions()
        with patch("database.trades_query.log_event") as warning:
            self.assertEqual(3, len(get_open_trades()))
        warning.assert_not_called()

    def test_warning_disk_failure_cannot_abort_emergency_closes(self):
        self.settings["max_concurrent_positions"] = 2
        self.seed_three_positions()
        self.next_status, self.next_qty, self.next_price = "filled", "3", "1.10"
        with patch("database.trades_query.log_event", side_effect=OSError("Event-log write failed")) as warning:
            self.guarded_tick()
        warning.assert_called()
        self.assert_flat_locked_once(count=6, quantity=9, pnl=-450)

    def test_invalid_limit_cannot_hide_existing_positions(self):
        from database import get_open_trades
        self.seed_three_positions()
        for bad in (None, "invalid", 0, -1):
            with self.subTest(limit=bad):
                self.settings["max_concurrent_positions"] = bad
                self.assertEqual(3, len(get_open_trades()))

    def test_accepted_exit_response_lost_then_restart(self):
        self.enter()
        self.next_status, self.next_qty, self.next_price = "filled", "3", "1.10"
        def lost_response(url, payload):
            self.post(url, payload)
            raise TimeoutError("Accepted exit but response lost")
        self.client._post.side_effect = lost_response
        self.guarded_tick()
        self.assertTrue(kill_lock.flatten_pending())
        self.assertEqual("open", self.rows()[0]["status"])
        self.assertEqual(2, len(self.submissions))
        self.restart()
        self.guarded_tick(valid=False)
        self.assert_flat_locked_once()

    def test_broker_snapshot_disconnect_never_confirms_flat(self):
        self.enter()
        self.next_status, self.next_qty, self.next_price = "filled", "3", "1.10"
        self.client.get_positions.side_effect = TimeoutError("Offline position snapshot")
        self.guarded_tick()
        self.assertTrue(kill_lock.flatten_pending())
        self.assertTrue(all(r["status"] == "closed" for r in self.rows()))
        self.restart()
        self.guarded_tick(valid=False)
        self.assert_flat_locked_once()


if __name__ == "__main__":
    unittest.main()
