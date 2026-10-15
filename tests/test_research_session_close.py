from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from trading.research_session_clock import session_close_if_open
from trading.research_order_exit import evaluate_exit
from trading.position_manager.manage import _resolve_latched_exit, _manage_open_position
from trading.position_manager.close import _close_position
from tests.test_research_order_execution import position


def at(value):
    return datetime.fromisoformat(value)


class ResearchSessionCloseTests(unittest.TestCase):
    def test_aapl_291_exit_fires_before_close_without_bars(self):
        trade = position('V2_GAP_FILL_RTH')
        entry = at('2026-10-14T09:51:00.642337-04:00')
        close = at('2026-10-14T16:00:00-04:00')
        self.assertFalse(evaluate_exit(trade, entry, close-timedelta(minutes=5, seconds=1), None,
                                       session_close=close)[0])
        self.assertEqual(evaluate_exit(trade, entry, close-timedelta(minutes=5), None,
                                      session_close=close), (True, 'research_session_close'))

    def test_early_close_and_overdue_next_open(self):
        trade = position('V2_GAP_FILL_RTH')
        close = at('2026-11-27T13:00:00-05:00')
        self.assertEqual(evaluate_exit(trade, at('2026-11-27T10:00:00-05:00'),
                         at('2026-11-27T12:55:00-05:00'), None, session_close=close),
                         (True, 'research_session_close'))
        self.assertEqual(evaluate_exit(trade, at('2026-10-14T09:51:00-04:00'),
                         at('2026-10-15T09:30:00-04:00'), None,
                         session_close=at('2026-10-15T16:00:00-04:00')),
                         (True, 'research_session_close'))

    def test_fresh_clock_cached_but_never_past_close(self):
        now = at('2026-11-27T12:59:58-05:00')
        broker = SimpleNamespace(base='paper', _get=Mock(return_value={
            'timestamp': now.isoformat(), 'is_open': True, 'next_close': '2026-11-27T13:00:00-05:00'}))
        self.assertEqual(session_close_if_open(broker, now).hour, 13)
        self.assertIsNone(session_close_if_open(broker, now+timedelta(seconds=2)))
        self.assertEqual(broker._get.call_count, 1)

    def test_holiday_closed_and_failed_clock_place_no_orders(self):
        for payload in ({'timestamp': '2026-11-26T10:00:00-05:00', 'is_open': False},
                        {'timestamp': '2026-11-25T10:00:00-05:00', 'is_open': True,
                         'next_close': '2026-11-26T16:00:00-05:00'}, {}):
            broker = SimpleNamespace(base='paper', _get=Mock(return_value=payload), place_option_order=Mock())
            trade = position('V2_GAP_FILL_RTH')
            with patch('trading.position_manager.close._now_et', return_value=at('2026-11-26T10:00:00-05:00')):
                _close_position(broker, trade, 2, 'research_session_close')
                _close_position(broker, trade, 2, 'research_session_close')
            broker.place_option_order.assert_not_called()
            self.assertEqual(broker._get.call_count, 1)

    def test_tradier_clock_uses_actual_next_change(self):
        now = at('2026-11-27T12:55:00-05:00')
        broker = SimpleNamespace(provider='tradier', market=SimpleNamespace(_get=Mock(return_value={
            'clock': {'state': 'open', 'timestamp': now.timestamp(), 'date': '2026-11-27', 'next_change': '13:00'}})))
        self.assertEqual(session_close_if_open(broker, now), at('2026-11-27T13:00:00-05:00'))

    def test_session_deadline_upgrades_existing_pending_exit(self):
        state = {'exit_pending_reason': 'research_stop', 'exit_pending_since': 'earlier'}
        self.assertEqual(_resolve_latched_exit(state, True, 'research_session_close',
                                              at('2026-10-14T15:55:00-04:00')),
                         (True, 'research_session_close'))
        self.assertEqual(state['exit_pending_since'], 'earlier')

    def test_manager_returns_before_quote_and_order_when_closed(self):
        broker, market = Mock(), Mock()
        with patch('trading.position_manager.manage.get_user_state', return_value={}), \
             patch('trading.position_manager.manage.get_user_risk'), \
             patch('trading.position_manager.manage.get_user_trade_log'), \
             patch('trading.research_session_clock.session_close_if_open', return_value=None):
            _manage_open_position(broker, market, position('V2_GAP_FILL_RTH'), 3000)
        market.get_option_quote.assert_not_called()
        broker.place_option_order.assert_not_called()

    def test_session_exit_allows_existing_market_fallback(self):
        broker = Mock()
        broker.place_option_order.return_value = None
        trade = position('V2_GAP_FILL_RTH')
        trade['ticker'] = 'AAPL'
        with patch('trading.research_session_clock.session_close_if_open', return_value=at('2026-10-14T16:00:00-04:00')), \
             patch('trading.position_manager.close.get_user_state', return_value={'positions': {101: {}}}), \
             patch('trading.position_manager.close.get_user_risk'), \
             patch('trading.position_manager.close.get_user_trade_log'), \
             patch('config.get_settings', return_value={'paper_trading': True}), \
             patch('trading.position_manager.close._snapshot_exit_annotations', return_value={}), \
             patch('trading.position_manager.close._reconcile_if_phantom', return_value=True):
            _close_position(broker, trade, 2, 'research_session_close', bid_price=1.99)
        self.assertTrue(broker.place_option_order.call_args.kwargs['allow_market_fallback'])
        self.assertEqual(broker.place_option_order.call_args.kwargs['order_type'], 'market')
        self.assertIsNone(broker.place_option_order.call_args.kwargs['limit_price'])
        self.assertEqual(broker.place_option_order.call_args.kwargs['position_intent'], 'sell_to_close')
