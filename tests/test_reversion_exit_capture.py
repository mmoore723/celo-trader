import unittest
from unittest.mock import patch

from strategy_health import reversion_exit, trend_exit, orb_exit
from strategy_health.authored_exit_summary import authored_summary, load_authored_exits
from tests import test_authored_exit_capture as fixtures
from tests.test_reversion_exit_measurement import seed
from tests.test_trend_exit_measurement import seed as trend_seed
from tests.test_orb_exit_measurement import seed as orb_seed


class ReversionExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def seed(self, name='reversion', **changes):
        self.f.seed(name,strategy_id=reversion_exit.STRATEGY_ID,protocol=reversion_exit.PROTOCOL,state=seed(),**changes)

    def test_all_forty_overlapping_plays_capture_without_orders(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['reason']=='underlying_stop' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_other_strategies_and_other_accounts_stay_separate(self):
        self.seed()
        self.seed('other',account='b')
        self.f.seed('trend',strategy_id=trend_exit.STRATEGY_ID,protocol=trend_exit.PROTOCOL,state=trend_seed())
        self.f.seed('orb',strategy_id=orb_exit.STRATEGY_ID,protocol=orb_exit.PROTOCOL,state=orb_seed())
        for name in ('V2_ORB_PULLBACK','CTX_ORB_NR7_OR_INSIDE'):
            self.f.seed(name,strategy_id=name,protocol=reversion_exit.PROTOCOL,state=seed())
        self.f.capture()
        self.assertEqual(['orb','reversion','trend'],[r['candidate_id'] for r in self.f.rows()])
        with self.f.connect() as conn:
            exits = load_authored_exits(conn,'a','2026-09-10')
            self.assertEqual(0,conn.execute('SELECT count(*) FROM research_strategy_exit_variants').fetchone()[0])
        result = authored_summary([{'candidate_id':name} for name in exits],exits,reversion_exit.PROTOCOL)
        self.assertEqual(1,result['option_results'])
        self.assertEqual(-83.3,result['net_one_contract_pnl'])
        self.assertNotIn('short_trail_comparison',result)

    def test_no_proof_is_unmeasurable_not_a_fabricated_exit(self):
        self.f.seed('reversion',strategy_id=reversion_exit.STRATEGY_ID,protocol=reversion_exit.PROTOCOL)
        self.f.capture()
        self.assertEqual(('unmeasurable','missing_exit_state'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))
        self.f.quote.assert_not_called()

    def test_matrix_has_actual_exit_without_relabeling_timer_results(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.f.capture()
        with patch('database.get_conn',self.f.connect), patch('database._now_et',return_value=self.f.now), patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[reversion_exit.STRATEGY_ID]},
        ), patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix = build_research_matrix()
        strategy = next(s for s in matrix['strategies'] if s['strategy_id']==reversion_exit.STRATEGY_ID)
        pair = next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('90-min check PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(0,pair['option_results'])
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])

    def test_frozen_vwap_target_is_priced_and_2r_protocol_reason_is_unchanged(self):
        self.seed()
        self.f.seed('impulse')
        self.f.frame.loc[5,['low','high']]=[99,105]
        self.f.capture()
        rows={r['candidate_id']:r for r in self.f.rows()}
        self.assertEqual(('priced','underlying_vwap_target'),(rows['reversion']['status'],rows['reversion']['reason']))
        self.assertEqual(('priced','underlying_2r_target'),(rows['impulse']['status'],rows['impulse']['reason']))
        self.f.quote.assert_called_once_with('XYZ')
