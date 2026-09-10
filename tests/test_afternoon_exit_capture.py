from datetime import datetime
import unittest
from unittest.mock import patch

from strategy_health import afternoon_exit, vwap_exit
from strategy_health.authored_exit_summary import authored_summary, load_authored_exits
from tests import test_authored_exit_capture as fixtures
from tests.test_afternoon_exit_measurement import seed
from tests.test_vwap_exit_measurement import seed as vwap_seed
from tests.test_impulse_exit_measurement import candles


class AfternoonExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.now=datetime(2026,9,10,13,16)
        self.f.frame=candles('2026-09-10T13:05',175)
        self.f.frame.loc[5,'low']=97
        self.f.quote.return_value['bid_date']='2026-09-10T13:15:30'

    def seed(self,name='afternoon',**changes):
        args=dict(strategy_id=afternoon_exit.STRATEGY_ID,protocol=afternoon_exit.PROTOCOL,state=seed())
        args.update(changes)
        self.f.seed(name,**args)
        with self.f.connect() as conn:
            conn.execute("UPDATE shadow_candidates SET observed_at='2026-09-10T13:05:01',trigger_bar='2026-09-10T13:05' WHERE candidate_id=?",(name,))
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T13:05:03' WHERE candidate_id=?",(name,))

    def test_forty_overlapping_plays_and_restart_capture_once(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['decision_at']=='2026-09-10T13:15:00' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_other_strategy_account_and_execution_source_are_separate(self):
        self.seed()
        self.seed('other',account='b')
        self.seed('execution',source='execution')
        self.seed('wrong_id',strategy_id='V2_SPY_AFTERNOON_FVG')
        self.seed('vwap',strategy_id=vwap_exit.STRATEGY_ID,protocol=vwap_exit.PROTOCOL,state=vwap_seed())
        self.f.capture()
        self.assertEqual(['afternoon','vwap'],[r['candidate_id'] for r in self.f.rows()])
        with self.f.connect() as conn:
            exits=load_authored_exits(conn,'a','2026-09-10')
            self.assertEqual(0,conn.execute('SELECT count(*) FROM research_strategy_exit_variants').fetchone()[0])
        summary=authored_summary([{'candidate_id':name} for name in exits],exits,afternoon_exit.PROTOCOL)
        self.assertEqual(1,summary['option_results'])
        self.assertEqual(-83.3,summary['net_one_contract_pnl'])

    def test_missing_time_config_proof_is_unmeasurable(self):
        self.seed(state={**seed(),'config':{**seed()['config'],'start_time':'13:00'}})
        self.f.capture()
        self.assertEqual(('unmeasurable','missing_exit_state'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))
        self.f.quote.assert_not_called()

    def test_matrix_keeps_timer_and_actual_exit_separate(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[afternoon_exit.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==afternoon_exit.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('90-min check PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(0,pair['option_results'])
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
