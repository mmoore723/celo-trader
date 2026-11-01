"""Outage regression: full liquidation is not gated by quote or bar availability."""
import json
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from trading.position_manager.manage import _manage_open_position
from trading.position_manager.exit_preflight import full_exit_reason, executable_quote

PAIRS = [
    ('TSLA', 'V2_ORB_PULLBACK'), ('SPY', 'V2_SPY_TREND_CONT'),
    ('SPY', 'V2_SPY_AFTERNOON_FVG'), ('SPY', 'V2_FAILED_OR_BREAK_VWAP_REVERSION'),
    ('TSLA', 'V2_TSLA_TWO_LEG_TREND_PULLBACK'),
    ('AMZN', 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'), ('TSLA', 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'),
    ('QQQ', 'V2_AFTERNOON_COMPRESSION_BREAKOUT'), ('AAPL', 'V2_GAP_FILL_RTH'),
    ('QQQ', 'V2_AFTERNOON_REVERSAL'), ('QQQ', 'V2_SPY_ORB_RSI_MACD_SHORT'),
    ('META', 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'),
    ('NVDA', 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'),
    ('SPY', 'RESEARCH_CTX_ORB_ATR10_V2'), ('QQQ', 'RESEARCH_FAILED_RANGE_V2'),
]
ENTRY = datetime.fromisoformat('2026-10-30T10:00:00-04:00')


class ExitOutageTests(unittest.TestCase):
    def run_tick(self, ticker, strategy, paper=True, pending=None, minutes=10,
                 quote=None, quote_error=None, session=True):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        rule = REVIEWED_STRATEGIES.get(strategy)
        trade = dict(id=101, ticker=ticker, strategy_id=strategy, entry_price=2.,
                     entry_time=ENTRY.isoformat(), contracts=2, paper=paper,
                     contract_symbol='OUTAGE_TEST', strategy_context_json=json.dumps({
                         'strategy_version': rule.version if rule else 'unknown',
                         'research_order_route': 'exact_research_v1'}))
        ps = {'exit_pending_reason': pending} if pending else {}
        state = {'positions': {101: ps}}
        now = ENTRY + timedelta(minutes=minutes)
        broker, market = Mock(), Mock()
        broker.get_positions.return_value = [{'symbol': 'OUTAGE_TEST', 'qty': '2'}]
        market.get_option_quote.return_value = quote
        market.get_option_quote.side_effect = quote_error
        with ExitStack() as stack:
            prefix = 'trading.position_manager.manage.'
            for name, value in [('get_user_state', state), ('get_user_risk', Mock()),
                                ('get_user_trade_log', []), ('_now_et', now)]:
                stack.enter_context(patch(prefix + name, return_value=value))
            persist = stack.enter_context(patch(prefix + '_persist_exit_latch'))
            stack.enter_context(patch('trading.research_session_clock.session_close_if_open',
                                     return_value=now.replace(hour=16, minute=0) if session else None))
            stack.enter_context(patch('trading.tsla_giveback_exit.evaluate_tsla_giveback',
                                     return_value=(False, 'hold')))
            errors = stack.enter_context(patch('database.log_event'))
            close = stack.enter_context(patch('trading.position_manager.close._close_position'))
            _manage_open_position(broker, market, trade, 3000)
            self.assertFalse(any(c.args and c.args[0] == 'ERROR' for c in errors.call_args_list))
        return close, persist, state, broker, market

    def test_all_pending_full_exits_retry_in_both_modes_despite_quote_failure(self):
        for ticker, strategy in PAIRS:
            for paper in (True, False):
                for error in (None, TimeoutError('provider outage')):
                    with self.subTest(strategy=strategy, ticker=ticker, paper=paper, error=error):
                        close, persist, state, broker, _ = self.run_tick(
                            ticker, strategy, paper, 'research_structural_stop', quote_error=error)
                        close.assert_called_once()
                        if strategy != 'V2_TSLA_TWO_LEG_TREND_PULLBACK':
                            self.assertTrue(close.call_args.kwargs['pricing_unavailable'])
                            self.assertIsNone(close.call_args.args[2])
                        self.assertEqual('research_structural_stop', close.call_args.args[3])
                        persist.assert_called_once()
                        broker.get_positions.assert_not_called()

    def test_six_deadlines_and_all_session_cutoffs_survive_missing_prices(self):
        from trading.v2_orb_paper_exit import V2_EXIT_MINUTES_BY_STRATEGY
        for ticker, strategy in PAIRS:
            for paper in (True, False):
                hold = V2_EXIT_MINUTES_BY_STRATEGY.get(strategy)
                if strategy == 'RESEARCH_FAILED_RANGE_V2':
                    hold = 30
                for minutes in ([hold] if hold else []) + [355]:
                    with self.subTest(strategy=strategy, ticker=ticker, paper=paper, minutes=minutes):
                        close, _, _, _, _ = self.run_tick(ticker, strategy, paper, minutes=minutes)
                        close.assert_called_once()
                        if minutes == 355:
                            self.assertEqual('research_session_close', close.call_args.args[3])

    def test_partial_latch_is_not_promoted_to_full_exit_before_deadline(self):
        for ticker, strategy in PAIRS:
            if strategy == 'V2_TSLA_TWO_LEG_TREND_PULLBACK':
                continue  # Existing TSLA special route, not changed by this preflight.
            with self.subTest(strategy=strategy):
                close, _, _, _, _ = self.run_tick(ticker, strategy, pending='stage1_research_atr10')
                close.assert_not_called()

    def test_deadline_supersedes_partial_but_not_earlier_full_exit(self):
        for pending, expected in [('stage1_profit_take', 'paid_markout'),
                                  ('research_structural_stop', 'research_structural_stop')]:
            close, _, _, _, _ = self.run_tick('SPY', 'V2_SPY_TREND_CONT', pending=pending, minutes=30)
            self.assertIn(expected, close.call_args.args[3])
        self.assertIsNone(full_exit_reason({'strategy_id': 'V2_SPY_TREND_CONT',
                                          'entry_time': ENTRY.isoformat()}, {},
                                         ENTRY + timedelta(minutes=29, seconds=59)))

    def test_valid_quote_preserves_limit_and_closed_session_blocks_submission(self):
        quote = {'bid': 1.8, 'ask': 1.9, 'mid': 1.85}
        close, _, _, _, _ = self.run_tick('SPY', 'V2_SPY_TREND_CONT',
                                         pending='research_structural_stop', quote=quote)
        self.assertEqual(1.8, close.call_args.args[2])
        self.assertFalse(close.call_args.kwargs['pricing_unavailable'])
        close, _, _, _, market = self.run_tick('SPY', 'V2_SPY_TREND_CONT',
                                              pending='research_structural_stop', session=False)
        close.assert_not_called()
        market.get_option_quote.assert_not_called()

    def test_invalid_quotes_never_become_limits(self):
        for quote in (None, {}, {'bid': 0, 'ask': 1}, {'bid': 2, 'ask': 1},
                      {'bid': float('nan'), 'ask': 2}, {'bid': 1, 'ask': float('inf')}):
            market = Mock()
            market.get_option_quote.return_value = quote
            self.assertEqual((None, None), executable_quote(market, 'TEST'))

    def test_unpriced_close_uses_market_and_requires_actual_fill_price(self):
        from trading.position_manager.close import _close_position
        trade = dict(id=101, ticker='QQQ', strategy_id='RESEARCH_FAILED_RANGE_V2',
                     contract_symbol='TEST', contracts=2, entry_price=2.)
        for paper in (True, False):
            broker = Mock()
            broker.place_option_order.return_value = {'filled_qty': '2'}
            with ExitStack() as stack:
                stack.enter_context(patch('trading.research_session_clock.session_close_if_open', return_value=ENTRY))
                stack.enter_context(patch('config.get_settings', return_value={'paper_trading': paper}))
                stack.enter_context(patch('trading.position_manager.close.get_user_state', return_value={'positions': {}}))
                stack.enter_context(patch('trading.position_manager.close._snapshot_exit_annotations', return_value={}))
                record = stack.enter_context(patch('database.close_trade'))
                capture = stack.enter_context(patch('database.record_paper_option_quote'))
                _close_position(broker, trade, None, 'research_structural_stop', pricing_unavailable=True)
                order = broker.place_option_order.call_args.kwargs
                self.assertEqual('market', order['order_type'])
                self.assertEqual('sell_to_close', order['position_intent'])
                self.assertEqual(2, order['qty'])
                self.assertIsNone(order['limit_price'])
                record.assert_not_called()
                capture.assert_not_called()
