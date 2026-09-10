import unittest
from unittest.mock import patch

from strategy_health import range_sweep_exit as module
from tests import test_authored_exit_capture as fixtures
from tests.test_range_sweep_exit_measurement import seed


class RangeSweepExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def seed(self,name='range',**changes):
        args=dict(strategy_id=module.STRATEGY_ID,protocol=module.PROTOCOL,state=seed())
        self.f.seed(name,**{**args,**changes})

    def test_forty_overlapping_plays_capture_once_without_allocation_limits(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['reason']=='underlying_stop' for r in self.f.rows()))
        self.assertTrue(all(r['decision_at']=='2026-09-10T10:11:00' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_other_accounts_and_mismatched_protocols_are_excluded(self):
        self.seed(); self.seed('other',account='b')
        self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.f.capture()
        self.assertEqual(['range'],[r['candidate_id'] for r in self.f.rows()])

    def test_missing_proof_and_late_ask_never_get_results(self):
        self.seed(state=None); self.seed('late')
        with self.f.connect() as conn:
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T10:06' WHERE candidate_id='late'")
        self.f.capture()
        self.assertEqual(['late_entry_quote','missing_exit_state'],[r['reason'] for r in self.f.rows()])
        self.assertTrue(all(r['status']=='unmeasurable' for r in self.f.rows()))
        self.f.quote.assert_not_called()

    def test_target_is_labeled_vwap_not_2r(self):
        self.seed()
        self.f.frame.loc[5,['high','low']]=[105,99]
        self.f.capture()
        self.assertEqual(('priced','underlying_vwap_target'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))

    def test_matrix_separates_actual_exit_from_30_minute_comparison(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed(); self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[module.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==module.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('30-min check PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(0,pair['option_results'])
        evidence=pair['authored_exit_evidence']
        self.assertEqual(1,evidence['option_results'])
        self.assertEqual(module.PROTOCOL,evidence['protocol'])
        self.assertEqual(-83.3,evidence['net_one_contract_pnl'])
