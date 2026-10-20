from contextlib import ExitStack
from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from trading.position_manager.manage import _manage_open_position


class TslaDeadlineTests(TestCase):
    def run_case(self, now, paper=True, pending=None, fill=None, session=True):
        trade = dict(id=224, ticker='TSLA', contracts=2, entry_price=4.0,
                     strategy_id='V2_TSLA_TWO_LEG_TREND_PULLBACK',
                     contract_symbol='TSLA261023C00380000', paper=paper,
                     entry_time='2026-10-19T10:00:00-04:00')
        state = {'positions': {224: dict(pending or {})}}
        broker, market = Mock(), Mock()
        broker.place_option_order.return_value = fill
        market.get_option_quote.side_effect = TimeoutError('missing quote')
        with ExitStack() as stack:
            for module in ('manage', 'close'):
                prefix = 'trading.position_manager.' + module
                stack.enter_context(patch(prefix + '.get_user_state', return_value=state))
                stack.enter_context(patch(prefix + '.get_user_risk'))
                stack.enter_context(patch(prefix + '.get_user_trade_log'))
                stack.enter_context(patch(prefix + '._now_et', return_value=datetime.fromisoformat(now)))
            stack.enter_context(patch('trading.research_session_clock.session_close_if_open',
                return_value=datetime.fromisoformat('2026-10-19T16:00:00-04:00') if session else None))
            stack.enter_context(patch('trading.tsla_giveback_exit.evaluate_tsla_giveback',
                                     return_value=(False, 'hold')))
            stack.enter_context(patch('config.get_settings', return_value={'paper_trading': paper}))
            persist = stack.enter_context(patch('trading.position_manager.manage._persist_exit_latch'))
            stack.enter_context(patch('trading.position_manager.close._snapshot_exit_annotations', return_value=None))
            stack.enter_context(patch('trading.position_manager.close._reconcile_if_phantom', return_value=False))
            stack.enter_context(patch('database.log_event'))
            closed = stack.enter_context(patch('database.close_trade'))
            _manage_open_position(broker, market, trade, 3000)
        return broker, market, state, persist, closed

    def test_due_without_quote_routes_market_in_both_modes(self):
        for paper in (True, False):
            broker, market, state, persist, _ = self.run_case('2026-10-19T11:30:00-04:00', paper)
            order = broker.place_option_order.call_args.kwargs
            self.assertEqual((order['order_type'], order['qty'], order['position_intent']),
                             ('market', 2, 'sell_to_close'))
            self.assertIsNone(order['limit_price'])
            market.get_option_quote.assert_not_called()
            self.assertIn('90m', state['positions'][224]['exit_pending_reason'])
            persist.assert_called_once()

    def test_before_deadline_does_not_submit(self):
        broker, _, _, _, _ = self.run_case('2026-10-19T11:29:59-04:00')
        broker.place_option_order.assert_not_called()

    def test_restored_pending_exit_survives_missing_quote(self):
        broker, market, state, _, _ = self.run_case(
            '2026-10-19T10:05:00-04:00',
            pending={'exit_pending_reason': 'structural_stop', 'exit_attempts': 2})
        self.assertEqual(broker.place_option_order.call_args.kwargs['order_context']['exit_reason'],
                         'structural_stop')
        self.assertEqual(state['positions'][224]['exit_attempts'], 3)
        market.get_option_quote.assert_not_called()

    def test_missing_fill_price_cannot_close_journal(self):
        _, _, state, _, closed = self.run_case(
            '2026-10-19T11:30:00-04:00', fill={'filled_qty': 2})
        closed.assert_not_called()
        self.assertTrue(state['positions'][224]['exit_pending_reason'])

    def test_closed_session_does_not_submit(self):
        broker, market, _, _, _ = self.run_case('2026-10-19T16:01:00-04:00', session=False)
        broker.place_option_order.assert_not_called()
        market.get_option_quote.assert_not_called()
