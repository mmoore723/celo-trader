from datetime import datetime
import json
import unittest
from unittest.mock import patch

from strategy_health import midday_exit, vwap_exit
from strategy_health.authored_exit_summary import authored_summary, load_authored_exits
from tests import test_authored_exit_capture as fixtures
from tests.test_midday_exit_measurement import seed
from tests.test_vwap_exit_measurement import seed as vwap_seed
from tests.test_impulse_exit_measurement import candles


class MiddayExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.now=datetime(2026,9,10,11,21)
        self.f.frame=candles('2026-09-10T11:10',290)
        self.f.frame.loc[5,'high']=105
        self.f.quote.return_value['bid_date']='2026-09-10T11:20:30'

    def seed(self,name='midday',**changes):
        args=dict(strategy_id=midday_exit.STRATEGY_ID,protocol=midday_exit.PROTOCOL,state=seed())
        args.update(changes)
        self.f.seed(name,**args)
        with self.f.connect() as conn:
            meta=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
            meta.update(underlying_stop=104,underlying_target=98)
            conn.execute("UPDATE shadow_candidates SET direction='bearish',metadata_json=? WHERE candidate_id=?",(json.dumps(meta),name))
            conn.execute("UPDATE shadow_candidates SET observed_at='2026-09-10T11:10:01',trigger_bar='2026-09-10T11:10' WHERE candidate_id=?",(name,))
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T11:10:03' WHERE candidate_id=?",(name,))

    def test_forty_overlapping_plays_and_restart_capture_once(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['decision_at']=='2026-09-10T11:20:00' for r in self.f.rows()))
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
        self.assertEqual(['midday','vwap'],[r['candidate_id'] for r in self.f.rows()])
        with self.f.connect() as conn:
            exits=load_authored_exits(conn,'a','2026-09-10')
            self.assertEqual(0,conn.execute('SELECT count(*) FROM research_strategy_exit_variants').fetchone()[0])
        summary=authored_summary([{'candidate_id':name} for name in exits],exits,midday_exit.PROTOCOL)
        self.assertEqual(1,summary['option_results'])
        self.assertEqual(-83.3,summary['net_one_contract_pnl'])

    def test_missing_time_config_proof_is_unmeasurable(self):
        self.seed(state={**seed(),'config':{**seed()['config'],'entry_start':'11:05'}})
        self.f.capture()
        self.assertEqual(('unmeasurable','missing_exit_state'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))
        self.f.quote.assert_not_called()

    def test_matrix_keeps_timer_and_actual_exit_separate(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[midday_exit.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==midday_exit.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual('Strategy-exit PF',strategy['exit_measurement']['pf_label'])
        self.assertEqual(1,pair['option_results'])
        self.assertTrue(all(r['option_results'] == 0 for r in pair['exit_comparison']))
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
