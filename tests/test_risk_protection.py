import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from risk.protection import (classify_risk_levels, display_risk_levels,
                             full_debit_risk, monitored_risk_fields, monitoring_failure)
from risk.manager import RiskManager


class ProtectionTests(unittest.TestCase):
    def timer(self):
        return dict(id=1, strategy_id='RESEARCH_QQQ_TREND_V2', ticker='QQQ', paper=1,
                    contract_symbol='QQQ_TEST', broker_account_id='account', status='open',
                    stop_price=2.1, target_price=3.5,
                    strategy_context_json=dict(strategy_version='2.1.0',
                                               research_order_route='exact_research_v1', underlying_stop=600))

    def levels(self, result):
        return {r['name']: r for r in result['levels']}

    def test_timer_references_do_not_become_stops(self):
        t = self.timer()
        r = self.levels(classify_risk_levels(t))
        self.assertEqual('Reference-only', r['option_stop']['state'])
        self.assertEqual('Reference-only', r['underlying_stop']['state'])
        self.assertEqual('Unavailable', r['support']['state'])
        self.assertEqual((), monitored_risk_fields(t, branch='reviewed'))

    def test_structural_policy_needs_monitoring_evidence(self):
        t = self.timer()
        t['strategy_id'] = 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'
        t['strategy_context_json'].update(strategy_version='research.2', underlying_target=620,
            authored_exit_protocol='impulse_structural_2r_completed5m_v1')
        fields = monitored_risk_fields(t, branch='reviewed')
        self.assertEqual(('underlying_stop', 'underlying_target'), fields)
        self.assertEqual('Unavailable', self.levels(classify_risk_levels(t))['underlying_stop']['state'])
        self.assertEqual('Enforced', self.levels(classify_risk_levels(t, monitored_fields=fields))['underlying_stop']['state'])
        self.assertEqual('Unavailable', self.levels(classify_risk_levels(t, monitored_fields=fields,
                            monitoring_reason='Missing bars'))['underlying_stop']['state'])

    def test_selected_timer_removes_structural_credit(self):
        from config.research_pair_policy import build
        t = self.timer()
        t['strategy_context_json']['selected_test_policy'] = build(t['strategy_id'],'QQQ','2.1.0',90)
        self.assertEqual((), monitored_risk_fields(t, branch='reviewed'))

    def test_stale_cross_account_and_closed_evidence_rejected(self):
        t = self.timer(); now = datetime.now(timezone.utc)
        s = classify_risk_levels(t, monitored_fields=['option_stop'])
        s['observed_at'] = now.isoformat()
        self.assertEqual('Enforced', self.levels(display_risk_levels(t,s,now))['option_stop']['state'])
        for changed, at in [(dict(t,broker_account_id='other'),now),(dict(t,paper=0),now),
                            (dict(t,status='closed'),now),(t,now+timedelta(seconds=61))]:
            self.assertNotEqual('Enforced',self.levels(display_risk_levels(changed,s,at))['option_stop']['state'])

    def test_bad_prices_and_context_are_unavailable(self):
        for value in (None, float('nan'), float('inf'), -1, 'bad'):
            t = dict(self.timer(),stop_price=value, strategy_context_json='{bad')
            self.assertEqual('Unavailable',self.levels(classify_risk_levels(t))['option_stop']['state'])

    def test_missing_quotes_cannot_claim_monitoring(self):
        self.assertIsNotNone(monitoring_failure(now=datetime.now(timezone.utc),quote={},frame=None,reason='hold'))

    def test_monitoring_rejects_gaps_future_and_stale_quotes(self):
        import pandas as pd
        now = pd.Timestamp('2026-11-10 10:05',tz='America/New_York')
        quote = dict(quote_received_at=now.isoformat(),quote_age_seconds=0,bid=1,ask=1.1)
        bars = pd.DataFrame({'time':pd.date_range(now-pd.Timedelta(minutes=3),periods=3,freq='min')})
        self.assertIsNone(monitoring_failure(now=now,quote=quote,frame=bars,reason='hold'))
        for q, f in [(dict(quote,quote_age_seconds=61),bars),
                     (dict(quote,quote_received_at=(now+pd.Timedelta(seconds=1)).isoformat()),bars),
                     (quote,bars.iloc[[0,2]])]:
            self.assertIsNotNone(monitoring_failure(now=now,quote=q,frame=f,reason='hold'))

    def test_no_global_risk_setting_or_trade_mutation(self):
        import copy
        t=self.timer(); before=copy.deepcopy(t)
        classify_risk_levels(t)
        self.assertEqual(before,t)

    @patch('risk.sizing.get_settings', return_value={'growth_mode':False})
    def test_all_routes_use_full_debit_and_fees(self, _settings):
        r = RiskManager(10000); r.effective_risk_pct=lambda _: .01
        for sid in (None, 'UNKNOWN', 'V2_SPY_TREND_CONT', 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'):
            self.assertEqual(0,r.calculate_contracts(1,10000,strategy_id=sid))
            qty=r.calculate_contracts(.4,10000,strategy_id=sid)
            self.assertEqual(2,qty)
            self.assertLessEqual(qty*full_debit_risk(.4),100)

    def test_bad_fee_assumption_rejected(self):
        with patch('config.COMMISSION_PER_CONTRACT',float('nan')):
            with self.assertRaises(ValueError): full_debit_risk(1)
