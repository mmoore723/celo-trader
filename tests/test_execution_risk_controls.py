"""Synthetic risk-budget and persistent halt regressions; no broker/network I/O."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from risk.manager import RiskManager
from risk.guard import DailyLossLimitReached
from risk import kill_lock
from trading.controls.panic import service_daily_loss_halt, _flatten_with_confirmed_fills


class SizingTests(unittest.TestCase):
    def setUp(self):
        self.risk = RiskManager(5000)
        self.risk.effective_risk_pct = Mock(return_value=.01)
        p = patch('risk.sizing.get_settings', return_value={'growth_mode':False})
        self.settings = p.start()
        self.addCleanup(p.stop)

    def test_no_forced_minimum(self):
        self.assertEqual(0, self.risk.calculate_contracts(8.5, 5000))

    def test_no_bootstrap_override(self):
        self.settings.return_value = {'growth_mode':True}
        self.assertEqual(0, self.risk.calculate_contracts(8.5, 4000))
        self.assertEqual(1, self.risk.calculate_contracts(2, 4000))

    def test_reviewed_timer_uses_full_debit(self):
        strategy = 'V2_TSLA_TWO_LEG_TREND_PULLBACK'
        self.assertEqual(2, self.risk.calculate_contracts(1, 5000))
        self.assertEqual(0, self.risk.calculate_contracts(1, 5000, strategy_id=strategy))
        self.assertEqual(1, self.risk.calculate_contracts(.5, 5000, strategy_id=strategy))

    def test_reviewed_structure_uses_full_debit(self):
        self.assertEqual(1, self.risk.entry_risk_fraction('CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'))

    def test_invalid_and_explicit_zero(self):
        for value in [0, -1, float('nan'), float('inf')]:
            with self.subTest(value=value):
                self.assertEqual(0, self.risk.calculate_contracts(value, 5000))
                self.assertEqual(0, self.risk.calculate_contracts(1, value))

    def test_budget_and_notional_ceiling_property(self):
        for growth in [False, True]:
            self.settings.return_value = {'growth_mode':growth}
            for balance in [500, 4000, 5000, 50000]:
                for rate in [.01, .03, .05, .5]:
                    self.risk.effective_risk_pct.return_value = rate
                    for ask in [.1, .5, 1, 2, 8.5, 25]:
                        for strategy in [None, 'V2_SPY_TREND_CONT']:
                            qty = self.risk.calculate_contracts(ask, balance, strategy_id=strategy)
                            fraction = self.risk.entry_risk_fraction(strategy)
                            cap = .45 if growth and balance < 5000 else (.3 if rate > .01 else .2)
                            self.assertLessEqual(qty * ask * 100 * fraction, balance * rate + 1e-8)
                            self.assertLessEqual(qty * ask * 100, balance * cap + 1e-8)

    def test_affordability_inverse(self):
        for strategy in [None, 'V2_SPY_TREND_CONT']:
            ask = self.risk.max_affordable_premium(5000, strategy_id=strategy)
            self.assertGreaterEqual(self.risk.calculate_contracts(
                self.risk.slippage_adjusted_entry(ask), 5000, strategy_id=strategy), 1)
            self.assertEqual(0, self.risk.calculate_contracts(
                self.risk.slippage_adjusted_entry(ask + .01), 5000, strategy_id=strategy))


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {'trading_enabled':True, 'daily_loss_hard_cap_pct':10, 'max_daily_loss_pct':.1}
        self.stack.enter_context(patch('risk.guard.get_settings', return_value=self.settings))
        self.stack.enter_context(patch('risk.guard.check_kill_lock', return_value=(False,None)))
        self.pnl = self.stack.enter_context(patch('risk.guard.get_todays_realized_pnl', return_value=0))
        self.state = {'day_start_balance':5000}
        self.stack.enter_context(patch('trading.state.get_user_state', return_value=self.state))
        self.stack.enter_context(patch('risk.guard.log_event'))
        self.lock = self.stack.enter_context(patch('risk.guard.set_kill_lock'))
        self.risk = RiskManager(5000)
        self.risk.is_trading_window = Mock(return_value=True)

    def test_equity_breach_persists_close_request(self):
        self.assertFalse(self.risk.can_trade(4500, False)[0])
        self.lock.assert_called_once_with()

    def test_existing_soft_lock_still_detects_hard_breach(self):
        with patch('risk.guard.check_kill_lock', return_value=(True, 'soft halt')):
            self.assertFalse(self.risk.can_trade(4400, False)[0])
        self.lock.assert_called_once_with()

    def test_zero_equity_still_requests_close(self):
        self.assertFalse(self.risk.can_trade(0, False)[0])
        self.lock.assert_called_once_with()

    def test_day_open_basis_not_diminishing_balance(self):
        self.pnl.return_value = -460
        self.assertTrue(self.risk.can_trade(4540, False)[0])
        self.lock.assert_not_called()

    def test_realized_breach_with_unrealized_recovery(self):
        self.pnl.return_value = -501
        self.assertFalse(self.risk.can_trade(5100, False)[0])
        self.lock.assert_called_once()

    def test_soft_halt_is_persisted_until_market_date_end(self):
        self.settings['max_daily_loss_pct'] = .05
        self.pnl.return_value = -251
        self.assertFalse(self.risk.can_trade(4900, False)[0])
        self.assertEqual('daily_loss_soft_cap', self.lock.call_args.kwargs['reason'])
        self.assertGreater(self.lock.call_args.kwargs['until'], datetime.utcnow())

    def test_close_bookkeeping_uses_same_check(self):
        self.pnl.return_value = -501
        with self.assertRaises(DailyLossLimitReached):
            self.risk.record_pnl(-1, 5000)
        self.lock.assert_called_once()

    def test_disk_failure_is_not_successful_halt(self):
        self.lock.side_effect = OSError('disk full')
        with self.assertRaises(OSError):
            self.risk.can_trade(4400, False)
        self.lock.side_effect = None
        self.assertFalse(self.risk.can_trade(5100, False)[0])
        self.assertEqual(2, self.lock.call_count)

    def test_missing_equity_or_database_blocks_entry(self):
        self.state['day_start_balance'] = 0
        with self.assertRaises(ValueError):
            self.risk.can_trade(5000, False)
        self.state['day_start_balance'] = 5000
        self.pnl.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            self.risk.can_trade(5000, False)


class PersistentHaltTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.settings = {'paper_trading':True, 'active_broker_account_id':'fixture-a'}
        self.stack.enter_context(patch('risk.kill_lock.get_settings', return_value=self.settings))
        self.directory = self.stack.enter_context(patch('risk.kill_lock.get_user_data_dir', return_value=self.root/'user-a'))
        self.stack.enter_context(patch('risk.kill_lock._KILL_LOCK_PATH', self.root/'legacy.json'))

    def test_pending_survives_expiry_and_fresh_read(self):
        kill_lock.set_kill_lock(until=datetime.utcnow()-timedelta(seconds=1))
        self.assertTrue(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])
        kill_lock.confirm_flattened()
        self.assertFalse(kill_lock.check_kill_lock()[0])

    def test_confirmed_flat_does_not_remove_active_freeze(self):
        kill_lock.set_kill_lock()
        kill_lock.confirm_flattened()
        self.assertFalse(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])

    def test_repeated_request_does_not_extend_freeze(self):
        first = kill_lock.set_kill_lock()
        self.assertEqual(first, kill_lock.set_kill_lock())

    def test_soft_to_hard_upgrade_once(self):
        first = kill_lock.set_kill_lock(until=datetime.utcnow()+timedelta(hours=1), reason='daily_loss_soft_cap')
        hard = kill_lock.set_kill_lock(hours=24)
        self.assertGreater(hard, first)
        self.assertEqual(hard, kill_lock.set_kill_lock(hours=24))
        self.assertTrue(kill_lock.flatten_pending())

    def test_user_account_and_mode_isolation(self):
        kill_lock.set_kill_lock()
        self.settings['active_broker_account_id'] = 'fixture-b'
        self.assertFalse(kill_lock.flatten_pending())
        self.settings['active_broker_account_id'] = 'fixture-a'
        self.settings['paper_trading'] = False
        self.assertFalse(kill_lock.flatten_pending())
        self.settings['paper_trading'] = True
        self.directory.return_value = self.root/'user-b'
        self.assertFalse(kill_lock.flatten_pending())

    def test_corrupt_state_fails_closed(self):
        kill_lock.set_kill_lock()
        from config import atomic_write_text
        atomic_write_text(kill_lock._lock_path(), '{broken')
        self.assertTrue(kill_lock.check_kill_lock()[0])
        with self.assertRaises(json.JSONDecodeError):
            kill_lock.flatten_pending()

    def test_cannot_manually_erase_pending_closes(self):
        kill_lock.set_kill_lock()
        with self.assertRaises(RuntimeError):
            kill_lock.clear_kill_lock()
        self.assertTrue(kill_lock.flatten_pending())

    def test_retry_rate_limit_restart_and_confirmation(self):
        kill_lock.set_kill_lock()
        state = {}
        with patch('trading.controls.panic.get_user_state', return_value=state), \
             patch('alerts.send_alert'), \
             patch('trading.controls.panic.time.monotonic', side_effect=[100,110,131,132]), \
             patch('trading.controls.panic._panic_close_all_positions', side_effect=[False,False,True]) as close:
            self.assertTrue(service_daily_loss_halt(Mock(),Mock(),user_id='fixture'))
            self.assertTrue(service_daily_loss_halt(Mock(),Mock(),user_id='fixture'))
            self.assertEqual(1,close.call_count)
            self.assertTrue(service_daily_loss_halt(Mock(),Mock(),user_id='fixture'))
            state.clear()  # new process has no in-memory retry state
            self.assertFalse(service_daily_loss_halt(Mock(),Mock(),user_id='fixture'))
            self.assertEqual(3,close.call_count)
        self.assertFalse(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])

    def test_guard_return_reaches_close_service_and_never_executes_entries(self):
        from trading.loop.daily_loss import run_guarded_execution
        risk = Mock()
        risk.check_daily_loss.side_effect = lambda balance: kill_lock.set_kill_lock()
        execute = Mock()
        with patch('trading.controls.panic.get_user_state',return_value={}), \
             patch('alerts.send_alert'), \
             patch('trading.controls.panic._panic_close_all_positions',return_value=False) as close:
            run_guarded_execution(risk=risk,balance=4400,balance_valid=True,
                                  collection_only=False,broker=Mock(),market=Mock(),
                                  user_id='fixture',execute=execute)
        close.assert_called_once()
        execute.assert_not_called()
        self.assertTrue(kill_lock.flatten_pending())

    def test_post_fill_exception_still_services_new_halt(self):
        from trading.loop.daily_loss import run_guarded_execution
        def execute():
            kill_lock.set_kill_lock()
            raise DailyLossLimitReached('post-fill loss')
        with patch('trading.controls.panic.get_user_state',return_value={}), \
             patch('alerts.send_alert'), \
             patch('trading.controls.panic._panic_close_all_positions',return_value=True) as close:
            with self.assertRaises(DailyLossLimitReached):
                run_guarded_execution(risk=Mock(),balance=5000,balance_valid=True,
                                      collection_only=False,broker=Mock(),market=Mock(),
                                      user_id='fixture',execute=execute)
        close.assert_called_once()
        self.assertFalse(kill_lock.flatten_pending())
        self.assertTrue(kill_lock.check_kill_lock()[0])

    def test_no_fresh_balance_blocks_entries_but_retries_existing_closes(self):
        from trading.loop.daily_loss import run_guarded_execution
        kill_lock.set_kill_lock()
        execute = Mock()
        with patch('trading.controls.panic.get_user_state',return_value={}), \
             patch('alerts.send_alert'), \
             patch('trading.controls.panic._panic_close_all_positions',return_value=False) as close:
            run_guarded_execution(risk=Mock(),balance=5000,balance_valid=False,
                                  collection_only=False,broker=Mock(),market=Mock(),
                                  user_id='fixture',execute=execute)
        close.assert_called_once()
        execute.assert_not_called()

    def test_maintenance_collection_only_never_closes(self):
        from trading.loop.daily_loss import run_guarded_execution
        kill_lock.set_kill_lock()
        execute = Mock()
        with patch('trading.loop.daily_loss.service_daily_loss_halt') as close:
            run_guarded_execution(risk=Mock(),balance=5000,balance_valid=True,
                                  collection_only=True,broker=Mock(),market=Mock(),
                                  user_id='fixture',execute=execute)
        close.assert_not_called()
        execute.assert_not_called()


class FlattenTests(unittest.TestCase):
    def environment(self, trades):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.pending = stack.enter_context(patch('broker.recovery.reconcile_orders', return_value=set()))
        self.trades = stack.enter_context(patch('database.get_open_trades', return_value=trades))
        self.close = stack.enter_context(patch('trading.position_manager.close._close_position'))
        broker, market = Mock(), Mock()
        broker.get_positions.return_value = []
        broker.get_open_orders.return_value = []
        market.get_option_quote.return_value = {'bid':1,'mid':1.1}
        return broker, market

    def test_pending_partial_exit_not_resubmitted(self):
        broker,market = self.environment([{'id':1,'contract_symbol':'FIXTURE'}])
        self.pending.return_value = {'FIXTURE'}
        self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        self.close.assert_not_called()

    def test_one_failed_close_does_not_starve_other_positions(self):
        broker,market = self.environment([{'id':1,'contract_symbol':'A'},{'id':2,'contract_symbol':'B'}])
        self.close.side_effect = [RuntimeError('offline'),None]
        self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        self.assertEqual(2,self.close.call_count)

    def test_missing_snapshot_never_means_flat(self):
        broker,market = self.environment([])
        broker.get_positions.return_value = None
        with self.assertRaises(ValueError):
            _flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close')

    def test_working_order_prevents_flat_confirmation_or_repeated_bulk_close(self):
        broker,market = self.environment([])
        broker.get_positions.return_value = [{'qty':1}]
        broker.get_open_orders.return_value = [{'symbol':'FIXTURE','side':'sell'}]
        self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        broker.close_all_positions.assert_not_called()
        broker.cancel_order.assert_not_called()

    def test_flat_requires_both_positions_and_orders(self):
        broker,market = self.environment([])
        self.assertTrue(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))


class RealizedPnlTests(unittest.TestCase):
    def test_market_date_and_account_scope(self):
        from risk.db_helpers import get_todays_realized_pnl
        from zoneinfo import ZoneInfo
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE trades (status TEXT, realized_pnl REAL, exit_time TEXT, broker_account_id TEXT)')
        db.executemany('INSERT INTO trades VALUES (?,?,?,?)', [
            ('closed',-30,'2026-09-11T15:40:00-04:00','a'),
            ('closed',10,'2026-09-12T03:59:59Z','a'),
            ('closed',999,'2026-09-12T04:00:00Z','a'),
            ('closed',999,'2026-09-11T03:59:59Z','a'),
            ('closed',999,'2026-09-11T15:40:00-04:00','b'),
            ('open',999,'2026-09-11T15:40:00-04:00','a'),
        ])
        with patch('risk.db_helpers.get_conn',return_value=db), \
             patch('config.get_settings',return_value={'active_broker_account_id':'a'}), \
             patch('risk.db_helpers.datetime') as clock:
            clock.now.return_value = datetime(2026,9,11,23,55,tzinfo=ZoneInfo('America/New_York'))
            self.assertEqual(-20,get_todays_realized_pnl())

    def test_database_failure_does_not_report_zero_loss(self):
        from risk.db_helpers import get_todays_realized_pnl
        with patch('config.get_settings',return_value={'active_broker_account_id':'a'}), \
             patch('risk.db_helpers.get_conn',side_effect=OSError('unavailable')):
            with self.assertRaises(RuntimeError):
                get_todays_realized_pnl()

    def test_missing_account_blocks_read(self):
        from risk.db_helpers import get_todays_realized_pnl
        with patch('config.get_settings',return_value={}):
            with self.assertRaises(RuntimeError):
                get_todays_realized_pnl()


if __name__ == '__main__':
    unittest.main()
