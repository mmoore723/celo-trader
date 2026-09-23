from contextlib import ExitStack
from datetime import datetime
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from research.engine.strategies.trend_continuation import TrendContinuation
from strategy_health.trend_exit import entry_state, PROTOCOL
from tests.test_impulse_exit_measurement import candles
from trading.trend_continuation_research_exit import evaluate_exit, uses_tested_session_close


def position(paper=True):
    return {'id': 123, 'ticker': 'SPY', 'strategy_id': 'V2_TREND_CONT', 'paper': paper,
            'contract_symbol': 'SPY_OPTION', 'direction': 'bullish', 'entry_price': 2,
            'strategy_context_json': json.dumps({'strategy_version': 'research.1',
                'authored_exit_protocol': PROTOCOL, 'authored_exit_state': entry_state(TrendContinuation()),
                'trigger_bar': '2026-09-23T14:50', 'underlying_stop': 98, 'underlying_target': 104})}


class TrendResearchSessionExecutionTests(unittest.TestCase):
    def run_tick(self, at, market_open, paper=True, collection_only=False):
        tick = importlib.import_module('trading.entry.tick')
        now = datetime.fromisoformat(at)
        new = position(paper)
        old = {**new, 'id': 124, 'strategy_id': 'V2_SPY_TREND_CONT', 'contract_symbol': 'OLD_OPTION'}
        state = {'_session_date': now.date().isoformat(), 'account_balance': 5000}
        risk = SimpleNamespace(ORB_STOP_PCT=.2, effective_risk_pct=lambda b:.38,
                               max_affordable_premium=lambda b:1900)
        broker = Mock()
        broker.is_market_open.return_value = market_open
        broker.get_account.return_value = {'equity': 5000, 'options_buying_power': 5000}
        broker.get_open_orders.return_value = [
            {'id': 'new-exit', 'symbol': 'SPY_OPTION', 'side': 'sell'},
            {'id': 'new-entry', 'symbol': 'SPY_OPTION', 'side': 'buy'},
            {'id': 'old-order', 'symbol': 'OLD_OPTION', 'side': 'sell'}]
        market = Mock()
        market.get_option_quote.return_value = {'mid': 2., 'bid': 1.95}
        settings = {'paper_trading': paper, 'last_known_balance': 5000, 'risk_per_trade': .38}
        with ExitStack() as stack:
            for name, value in [('_now_et', now), ('get_user_state', state), ('get_user_risk', risk),
                                ('get_settings', settings), ('get_open_trades', [new, old]),
                                ('_check_ghost_positions', None), ('check_kill_lock', (False, ''))]:
                stack.enter_context(patch.object(tick, name, return_value=value))
            for name in ('atomic_write_json', 'log_event', 'route_signals'):
                stack.enter_context(patch.object(tick, name))
            for name in ('pathlib.Path.write_text', 'config.save_settings', 'trading.recovery_state.restore_entries'):
                stack.enter_context(patch(name))
            stack.enter_context(patch('config.get_settings', return_value=settings))
            stack.enter_context(patch('config.get_risk_tier', return_value='manual'))
            stack.enter_context(patch('config.get_maintenance_state', return_value={
                'maintenance_mode': collection_only, 'collection_only': collection_only}))
            manage = stack.enter_context(patch.object(tick, '_manage_open_position'))
            close = stack.enter_context(patch.object(tick, '_close_position'))
            tick._tick(broker, market, scan_ticker='', execution_only=True)
            self.assertFalse(tick.route_signals.called)
        return new, old, manage, close, broker

    def test_355_keeps_tested_exit_and_closes_legacy_positions_in_both_modes(self):
        for paper in (True, False):
            new, old, manage, close, broker = self.run_tick('2026-09-23T15:55:00-04:00', True, paper)
            self.assertEqual(new, manage.call_args.args[2])
            self.assertEqual(1, manage.call_count)
            self.assertEqual(old, close.call_args.args[1])
            self.assertEqual(1, close.call_count)
            self.assertEqual(['new-entry', 'old-order'], [c.args[0] for c in broker.cancel_order.call_args_list])

    def test_equity_market_close_does_not_skip_the_tested_exit_or_allow_entries(self):
        for paper in (True, False):
            new, _, manage, close, _ = self.run_tick('2026-09-23T16:00:00-04:00', False, paper)
            self.assertEqual(new, manage.call_args.args[2])
            self.assertEqual(1, manage.call_count)
            close.assert_not_called()

    def test_closed_market_before_session_deadline_does_not_create_order_authority(self):
        _, _, manage, close, _ = self.run_tick('2026-09-23T14:00:00-04:00', False)
        manage.assert_not_called()
        close.assert_not_called()

    def test_collection_only_still_prohibits_all_orders_after_close(self):
        _, _, manage, close, broker = self.run_tick('2026-09-23T16:00:00-04:00', False, collection_only=True)
        manage.assert_not_called()
        close.assert_not_called()
        broker.cancel_order.assert_not_called()

    def test_frozen_research_exit_holds_at_355_and_exits_at_4(self):
        for paper in (True, False):
            trade = position(paper)
            data = candles('2026-09-23T14:50', 70)
            self.assertEqual((False, 'hold'), evaluate_exit(trade, '2026-09-23T14:50:01',
                datetime.fromisoformat('2026-09-23T15:55:00-04:00'), data))
            self.assertEqual((True, 'trend_cont_session_flatten'), evaluate_exit(trade, '2026-09-23T14:50:01',
                datetime.fromisoformat('2026-09-23T16:00:00-04:00'), data))

    def test_only_exact_version_and_supported_ticker_use_this_session_close(self):
        trade = position()
        self.assertTrue(uses_tested_session_close(trade))
        for change in ({'ticker':'TSLA'}, {'strategy_id':'V2_SPY_TREND_CONT'},
                       {'strategy_context_json':'{}'}, {'strategy_context_json':'bad'}):
            self.assertFalse(uses_tested_session_close({**trade, **change}))
