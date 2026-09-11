import json
import unittest
from unittest.mock import patch

from strategy_health import rsi_macd_exit, orb_exit
from tests import test_authored_exit_capture as fixtures
from tests.test_rsi_macd_exit_measurement import seed
from tests.test_orb_exit_measurement import seed as orb_seed


class RsiMacdExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.frame.loc[5,'high']=103

    def seed(self, name='rsi', **changes):
        args=dict(strategy_id=rsi_macd_exit.STRATEGY_ID,protocol=rsi_macd_exit.PROTOCOL,state=seed())
        self.f.seed(name,**{**args,**changes})
        with self.f.connect() as conn:
            meta=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
            meta.update(underlying_stop=102,underlying_target=96)
            conn.execute("UPDATE shadow_candidates SET direction='bearish',metadata_json=? WHERE candidate_id=?",(json.dumps(meta),name))

    def test_forty_overlapping_plays_capture_once_without_allocation_limits(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['reason']=='underlying_stop' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_other_account_and_confirmed_orb_stay_separate(self):
        self.seed(); self.seed('other',account='b')
        self.f.seed('orb',strategy_id=orb_exit.STRATEGY_ID,protocol=orb_exit.PROTOCOL,state=orb_seed())
        self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.f.capture()
        self.assertEqual(['orb','rsi'],[r['candidate_id'] for r in self.f.rows()])
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))

    def test_missing_proof_cannot_be_priced(self):
        self.seed(state=None)
        self.f.capture()
        self.assertEqual(('unmeasurable','missing_exit_state'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))
        self.f.quote.assert_not_called()

    def test_short_target_gets_1_5r_reason(self):
        self.seed()
        self.f.frame.loc[5,['high','low']]=[101,95]
        self.f.capture()
        self.assertEqual(('priced','underlying_1_5r_target'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))

    def test_matrix_separates_original_timer_and_structural_exit(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed(); self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[rsi_macd_exit.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==rsi_macd_exit.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('Strategy-exit PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(1,pair['option_results'])
        self.assertTrue(all(r['option_results'] == 0 for r in pair['exit_comparison']))
        evidence=pair['authored_exit_evidence']
        self.assertEqual(1,evidence['option_results'])
        self.assertEqual(rsi_macd_exit.PROTOCOL,evidence['protocol'])
        self.assertEqual(-83.3,evidence['net_one_contract_pnl'])
