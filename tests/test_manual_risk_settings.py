"""User-selected sizing survives API round trips and account tier boundaries."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from starlette.requests import Request

from api.models.settings import Settings
from api.routes.settings import get_settings_endpoint, save_settings_endpoint
from config.risk_constants import get_risk_tier
from risk.manager import RiskManager


class ManualRiskTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(risk_per_trade=.38, growth_mode=True, max_position_dollars_pct=38,
                          paper_trading=True, broker_provider='alpaca', max_concurrent_positions=3,
                          daily_loss_hard_cap_pct=30, max_daily_loss_pct=.10, watchlist=['SPY'])
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ('config.get_settings', 'config.settings_store.get_settings', 'risk.sizing.get_settings'):
            stack.enter_context(patch(name, side_effect=lambda:dict(self.saved)))
        self.risk = RiskManager(3746.15)

    def test_manual_38_is_not_replaced_by_balance_tier(self):
        for balance in (3746.15, 4999, 5000, 25000, 50000):
            self.assertEqual(.38, get_risk_tier(balance))
            self.assertEqual(.38, self.risk.effective_notional_pct(balance))

    def test_reported_tsla_contract_fits_user_budget(self):
        entry = self.risk.slippage_adjusted_entry(6.15)
        self.assertAlmostEqual(6.4575, entry)
        qty = self.risk.calculate_contracts(entry, 3746.15, strategy_id='V2_TSLA_TWO_LEG_TREND_PULLBACK')
        self.assertEqual(2, qty)
        self.assertLessEqual(qty*entry*100, 3746.15*.38)

    def test_user_can_lower_risk_and_next_sizing_reads_it(self):
        self.saved['risk_per_trade'] = .05
        self.assertEqual(0, self.risk.calculate_contracts(6.4575, 3746.15,
                         strategy_id='V2_TSLA_TWO_LEG_TREND_PULLBACK'))

    def test_manual_premium_cap_applies_to_total_cost(self):
        self.saved['max_position_dollars_pct'] = 10
        self.assertEqual(.10, self.risk.effective_notional_pct(5000))
        self.assertEqual(5, self.risk.calculate_contracts(1, 5000, strategy_id='V2_SPY_TREND_CONT'))

    def test_affordability_and_sizing_share_manual_limits(self):
        for balance in (3746.15, 5000, 50000):
            ask = self.risk.max_affordable_premium(balance, strategy_id='V2_SPY_TREND_CONT')
            self.assertGreaterEqual(self.risk.calculate_contracts(self.risk.slippage_adjusted_entry(ask),
                                    balance, strategy_id='V2_SPY_TREND_CONT'), 1)
            self.assertEqual(0, self.risk.calculate_contracts(self.risk.slippage_adjusted_entry(ask+.01),
                             balance, strategy_id='V2_SPY_TREND_CONT'))

    def test_automatic_behavior_unchanged_when_chosen(self):
        self.saved['risk_per_trade'] = None
        for balance, expected in ((4000,.05),(5000,.03),(25000,.02),(50000,.01)):
            self.assertEqual(expected, get_risk_tier(balance))

    def test_invalid_saved_manual_value_cannot_silently_fall_back(self):
        for invalid in (0, -1, 1.01, float('nan'), float('inf'), 'bad', True):
            self.saved['risk_per_trade'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): get_risk_tier(4000)

    def test_api_get_save_get_preserves_manual_choice_and_other_limits(self):
        self.saved['risk_per_trade'] = None
        initial = get_settings_endpoint()
        payload = initial.model_copy(update={'risk_auto':False, 'risk_pct':38})
        request = Request({'type':'http','method':'POST','path':'/','headers':[]})
        request.state.user_id = 'admin'
        with patch('config.save_settings', side_effect=self.saved.update), \
             patch('database.record_strategy_setting_changes'), \
             patch('trading.state.get_user_state', return_value={}):
            save_settings_endpoint(payload, request)
            displayed = get_settings_endpoint()
            self.assertFalse(displayed.risk_auto)
            self.assertEqual(38, displayed.risk_pct)
            self.assertEqual(.38, get_risk_tier(3746.15))
            save_settings_endpoint(displayed.model_copy(update={'display_timezone':'UTC'}), request)
        self.assertEqual(.38, self.saved['risk_per_trade'])
        self.assertEqual((38,3,30,.1,True), tuple(self.saved[k] for k in
            ('max_position_dollars_pct','max_concurrent_positions','daily_loss_hard_cap_pct',
             'max_daily_loss_pct','paper_trading')))

    def test_settings_schema_rejects_invalid_percentages(self):
        values = get_settings_endpoint().model_dump()
        for field in ('risk_pct','max_position_dollars_pct'):
            for invalid in (0, -1, 101, float('nan'), float('inf')):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValidationError):
                    Settings(**{**values,field:invalid})

    def test_preview_and_final_order_use_same_cap(self):
        source = (Path(__file__).resolve().parents[1]/'trading/entry/tick.py').read_text()
        self.assertIn('_preview_notional_pct = _risk.effective_notional_pct(balance)', source)
        self.assertIn('_notional_pct = _risk.effective_notional_pct(balance)', source)
        self.assertNotIn('_preview_growth', source)
        self.assertNotIn('_in_bs_clamp', source)


if __name__ == '__main__':
    unittest.main()
