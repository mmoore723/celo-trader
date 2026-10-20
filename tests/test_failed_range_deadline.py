from contextlib import ExitStack
from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from tests.test_research_order_execution import position
from trading.position_manager.manage import _manage_open_position


class FailedRangeDeadlineTests(TestCase):
    def run_case(self, now, paper=True, session=True):
        trade = position('RESEARCH_FAILED_RANGE_V2')
        trade.update(id=293, ticker='QQQ', contracts=6, entry_price=1.61,
                     entry_time='2026-10-14T10:35:27.447130-04:00')
        state = {'positions': {}}
        broker, market = Mock(), Mock()
        broker.place_option_order.return_value = None
        market.get_option_quote.side_effect = TimeoutError('quote unavailable')
        with ExitStack() as stack:
            for module in ('manage', 'close'):
                prefix = 'trading.position_manager.' + module
                stack.enter_context(patch(prefix + '.get_user_state', return_value=state))
                stack.enter_context(patch(prefix + '.get_user_risk'))
                stack.enter_context(patch(prefix + '.get_user_trade_log'))
                stack.enter_context(patch(prefix + '._now_et', return_value=datetime.fromisoformat(now)))
            stack.enter_context(patch('trading.research_session_clock.session_close_if_open',
                return_value=datetime.fromisoformat('2026-10-14T16:00:00-04:00') if session else None))
            stack.enter_context(patch('config.get_settings', return_value={'paper_trading': paper}))
            stack.enter_context(patch('trading.position_manager.manage._persist_exit_latch'))
            stack.enter_context(patch('trading.position_manager.close._snapshot_exit_annotations', return_value=None))
            stack.enter_context(patch('trading.position_manager.close._reconcile_if_phantom', return_value=True))
            stack.enter_context(patch('database.log_event'))
            _manage_open_position(broker, market, trade, 3000)
        return broker, market, state

    def test_293_due_exit_does_not_wait_for_quotes_in_either_mode(self):
        for paper in (True, False):
            broker, market, state = self.run_case('2026-10-14T11:05:27.447130-04:00', paper)
            broker.place_option_order.assert_called_once()
            order = broker.place_option_order.call_args.kwargs
            self.assertEqual((order['order_type'], order['qty'], order['position_intent']),
                             ('market', 6, 'sell_to_close'))
            self.assertIsNone(order['limit_price'])
            self.assertEqual(order['order_context']['exit_reason'], 'research_failed_range_30m')
            market.get_option_quote.assert_not_called()
            self.assertEqual(state['positions'][293]['exit_attempts'], 1)

    def test_not_due_does_not_exit(self):
        broker, _, _ = self.run_case('2026-10-14T11:05:26-04:00')
        broker.place_option_order.assert_not_called()

    def test_closed_session_does_not_submit(self):
        broker, market, _ = self.run_case('2026-10-14T11:05:28-04:00', session=False)
        broker.place_option_order.assert_not_called()
        market.get_option_quote.assert_not_called()

    def test_session_deadline_takes_precedence(self):
        broker, _, _ = self.run_case('2026-10-14T15:55:00-04:00')
        self.assertEqual(broker.place_option_order.call_args.kwargs['order_context']['exit_reason'],
                         'research_session_close')
