"""Reproduce the selection/sizing mismatch; this is not a return forecast."""
from datetime import datetime
import unittest
from unittest.mock import patch

from risk.manager import RiskManager
from trading.entry.contract import select_reviewed_v2_contract


class QuoteFixture:
    def get_expirations(self, ticker, **kwargs):
        return ['2026-09-18']

    def get_option_chain(self, ticker, expiry, side):
        return [dict(symbol='NEAR',strike=766,bid=5.99,ask=6),
                dict(symbol='FAR',strike=780,bid=1.18,ask=1.20)]


class AffordabilityDiagnostic(unittest.TestCase):
    def test_position_budget_can_choose_unsizeable_contract_despite_affordable_alternative(self):
        risk=RiskManager(5000)
        # Freeze the audited $5,000 tier. Neither fixture can submit an order.
        with patch('risk.sizing.get_settings',return_value={'growth_mode':True}), \
             patch.object(risk,'effective_risk_pct',return_value=.03), \
             patch('trading.entry.contract._now_et',return_value=datetime.fromisoformat('2026-09-11T12:00:00-04:00')):
            args=(QuoteFixture(),'SPY','bullish',765)
            current,_=select_reviewed_v2_contract(*args,5000*.38,strategy_id='V2_SPY_TREND_CONT')
            self.assertEqual('NEAR',current['symbol'])
            quantity=risk.calculate_contracts(risk.slippage_adjusted_entry(current['ask']),5000,
                                              strategy_id='V2_SPY_TREND_CONT')
            self.assertEqual(0,quantity)
            cap=risk.max_affordable_premium(5000,strategy_id='V2_SPY_TREND_CONT')
            self.assertEqual(1.42,cap)
            alternate,_=select_reviewed_v2_contract(*args,cap*100,strategy_id='V2_SPY_TREND_CONT')
            self.assertEqual('FAR',alternate['symbol'])
            self.assertEqual(1,risk.calculate_contracts(risk.slippage_adjusted_entry(alternate['ask']),5000,
                                                      strategy_id='V2_SPY_TREND_CONT'))
            # FAR is a different exposure, not a validated replacement. Leave
            # live selection unchanged until same-entry quote testing is done.


if __name__=='__main__':
    unittest.main()
