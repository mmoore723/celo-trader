"""Audit regression fixtures, updated after the approved execution-risk repair.

The original findings on production 30dd69f remain in SEPTEMBER_REPAIR_DECISION.md.
"""
from contextlib import ExitStack
from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from risk.manager import RiskManager
from trading.controls.panic import _flatten_with_confirmed_fills, _panic_close_all_positions


class LossControlAuditTests(unittest.TestCase):
    def guard_environment(self, *, equity_start=5000, realized=0, locked=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('risk.guard.get_settings', return_value={
            'trading_enabled':True, 'daily_loss_hard_cap_pct':10, 'max_daily_loss_pct':.10}))
        stack.enter_context(patch('risk.guard.check_kill_lock', return_value=(locked, 'fixture lock' if locked else None)))
        stack.enter_context(patch('risk.guard.get_todays_realized_pnl', return_value=realized))
        stack.enter_context(patch('trading.state.get_user_state', return_value={'day_start_balance':equity_start}))
        stack.enter_context(patch('risk.guard.log_event'))
        kill = stack.enter_context(patch('risk.guard.set_kill_lock', return_value=datetime(2026,9,12,12)))
        risk = RiskManager(5000)
        risk.is_trading_window = Mock(return_value=True)
        return risk, kill

    def test_unrealized_hard_cap_sets_lock_but_returns_entry_denial(self):
        risk, kill = self.guard_environment()
        result = risk.can_trade(4490, has_open_position=False)
        self.assertFalse(result[0])
        self.assertIn('equity down', result[1])
        self.assertTrue(risk.daily_limit_hit)
        kill.assert_called_once()
        # The revised loop services the persisted close request on return too.

    def test_existing_lock_returns_denial_without_creating_another_lock(self):
        risk, kill = self.guard_environment(locked=True)
        self.assertEqual((False,'fixture lock'), risk.can_trade(4900,False))
        kill.assert_not_called()

    def test_current_balance_no_longer_changes_day_open_threshold(self):
        risk, kill = self.guard_environment(realized=-460)
        allowed, _ = risk.can_trade(4540,False)
        self.assertTrue(allowed)
        kill.assert_not_called()

    def test_below_threshold_can_trade_when_other_guards_pass(self):
        risk, kill = self.guard_environment(realized=-100)
        self.assertEqual((True,'OK'), risk.can_trade(4900,False))
        kill.assert_not_called()

    def test_pending_exit_is_not_submitted_twice_or_reported_flat(self):
        trade = {'id':1,'contract_symbol':'FIXTURE','entry_price':2}
        broker, market = Mock(), Mock()
        with patch('broker.recovery.reconcile_orders',return_value={'FIXTURE'}), \
             patch('database.get_open_trades',return_value=[trade]), \
             patch('trading.position_manager.close._close_position') as close:
            self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        close.assert_not_called()
        broker.close_all_positions.assert_not_called()

    def test_unconfirmed_close_remains_open(self):
        trade = {'id':1,'contract_symbol':'FIXTURE','entry_price':2}
        broker, market = Mock(), Mock()
        market.get_option_quote.return_value={'bid':1.5,'ask':1.55,'mid':1.525}
        with patch('broker.recovery.reconcile_orders',return_value=set()), \
             patch('database.get_open_trades',return_value=[trade]), \
             patch('trading.position_manager.close._close_position') as close:
            self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        close.assert_called_once()
        self.assertEqual('kill_lock_force_close',close.call_args.args[3])
        broker.get_positions.assert_not_called()

    def test_confirmed_local_close_still_checks_broker_position(self):
        trade = {'id':1,'contract_symbol':'FIXTURE','entry_price':2}
        broker, market = Mock(), Mock()
        broker.get_positions.side_effect=[[{'qty':1}], [{'qty':1}]]
        broker.get_open_orders.return_value=[]
        broker.close_all_positions.return_value=True
        market.get_option_quote.return_value={'bid':1.5}
        with patch('broker.recovery.reconcile_orders',return_value=set()), \
             patch('database.get_open_trades',side_effect=[[trade],[]]), \
             patch('trading.position_manager.close._close_position'):
            self.assertFalse(_flatten_with_confirmed_fills(broker,market,reason='kill_lock_force_close'))
        broker.close_all_positions.assert_called_once()

    def test_internal_panic_preserves_unconfirmed_position_state(self):
        state={'positions':{'one':{}},'open_trades':[{'id':1}], 'open_trade':{'id':1}}
        with patch('trading.controls.panic.get_user_state',return_value=state), \
             patch('trading.controls.panic._flatten_with_confirmed_fills',return_value=False), \
             patch('trading.controls.panic._refresh_session_pnl'), \
             patch('database.log_event'):
            _panic_close_all_positions(Mock(),Mock(),user_id='fixture')
        self.assertEqual('kill_locked',state['status'])
        self.assertEqual([{'id':1}],state['open_trades'])
        self.assertIn('one',state['positions'])

    def test_minimum_contract_cannot_exceed_nominal_one_percent_risk(self):
        risk=RiskManager(5000)
        risk.effective_risk_pct=Mock(return_value=.01)
        with patch('risk.sizing.get_settings',return_value={'growth_mode':False}):
            quantity=risk.calculate_contracts(8.50,5000)
        self.assertEqual(quantity,0)
        self.assertLessEqual(quantity*8.50*100*risk.ORB_STOP_PCT,5000*.01)

    def test_bootstrap_minimum_cannot_override_low_risk_setting(self):
        risk=RiskManager(4000)
        risk.effective_risk_pct=Mock(return_value=.01)
        with patch('risk.sizing.get_settings',return_value={'growth_mode':True}):
            quantity=risk.calculate_contracts(8.50,4000)
        self.assertEqual(quantity,0)
        self.assertLessEqual(quantity*8.50*100*risk.ORB_STOP_PCT,4000*.01)


if __name__ == '__main__':
    unittest.main()
