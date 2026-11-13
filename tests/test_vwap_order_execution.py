import unittest
from datetime import timedelta
from unittest.mock import patch
import pandas as pd
from config.admin_strategy_overrides import updates
from config.strategy_catalog import reviewed_strategy_integrity_errors, enabled_reviewed_strategy_ids
from strategies import research_orders
from trading.tested_strategy_research import evaluate_tested_research
from tests.test_vwap_exit_measurement import setup_bars
from tests.test_momentum_exit_measurement import frame

SID = 'V2_VWAP_PULLBACK'

class VwapOrderTests(unittest.TestCase):
    def test_registration_is_exact_and_preserves_account_settings(self):
        self.assertEqual({}, reviewed_strategy_integrity_errors())
        changes = updates({}, SID, 'AMZN', 'research.1', True, 'admin', exit_minutes=90, contract_policy='closest_otm_150_1000')
        self.assertNotIn('paper_trading', changes)
        self.assertNotIn('risk_per_trade', changes)
        for paper in (True, False):
            self.assertIn(SID, enabled_reviewed_strategy_ids({**changes, 'paper_trading':paper}, ticker='AMZN'))
            self.assertNotIn(SID, enabled_reviewed_strategy_ids(changes, ticker='QQQ'))
        qqq = updates({}, SID, 'QQQ', 'research.1', True, 'admin')
        self.assertIn('APPROVED_'+SID, enabled_reviewed_strategy_ids(qqq, ticker='QQQ'))
        self.assertNotIn('APPROVED_'+SID, enabled_reviewed_strategy_ids(qqq, ticker='AMZN'))

    def test_real_entry_parity_and_duplicate_protection(self):
        for direction in (1, -1):
            bars = setup_bars(direction, 1)[:25]
            data = frame(bars)
            now = bars[-1].timestamp + timedelta(minutes=5)
            with patch.object(research_orders, '_emitted', {}), patch('trading.tested_strategy_research._emitted', set()), patch('database.load_scanner_candles', return_value=pd.DataFrame()):
                expected = evaluate_tested_research(data, 'AMZN', [SID], scope='research', now=now)
                actual = research_orders.evaluate(data, 'AMZN', execution_scope='orders', now=now, strategy_id=SID)
                self.assertEqual(1, len(expected))
                self.assertIsNotNone(actual)
                levels = actual.meta['structural_levels']
                self.assertEqual('captured', levels['status'])
                self.assertEqual(bars[-2].low if direction == 1 else bars[-2].high,
                                 levels['support'] if direction == 1 else levels['resistance'])
                for key in ('support', 'resistance', 'basis', 'source_completed_at'):
                    self.assertEqual(expected[0].meta['structural_levels'][key], levels[key])
                self.assertEqual(expected[0].direction, actual.direction)
                for key in ('underlying_stop','underlying_target','authored_exit_protocol','authored_exit_state'):
                    self.assertEqual(expected[0].meta[key], actual.meta[key])
                self.assertIsNone(research_orders.evaluate(data, 'AMZN', execution_scope='orders', now=now, strategy_id=SID))

    def test_selected_timer_works_without_quote(self):
        from tests.test_failed_range_deadline import FailedRangeDeadlineTests
        from tests.test_research_order_execution import position
        from config.research_pair_policy import build
        trade = position(SID, selected_test_policy=build(SID,'AMZN','research.1',90,'closest_otm_150_1000'))
        with patch('tests.test_failed_range_deadline.position', return_value=trade):
            broker, market, state = FailedRangeDeadlineTests().run_case('2026-10-14T12:05:28-04:00', ticker='AMZN')
        self.assertEqual('selected_test_90m', broker.place_option_order.call_args.kwargs['order_context']['exit_reason'])
        self.assertEqual('market', broker.place_option_order.call_args.kwargs['order_type'])
        market.get_option_quote.assert_not_called()
