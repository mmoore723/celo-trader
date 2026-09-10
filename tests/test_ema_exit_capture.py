from datetime import datetime
import json
import unittest
from unittest.mock import patch

from strategy_health import ema_exit, reversion_exit
from tests import test_authored_exit_capture as fixtures
from tests.test_ema_exit_measurement import seed
from tests.test_reversion_exit_measurement import seed as reversion_seed
from tests.test_impulse_exit_measurement import candles


class EmaExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.now=datetime(2026,9,10,10,31)
        self.f.frame=candles('2026-09-10T10:00',31)
        self.f.frame.loc[25,'low']=97
        self.f.quote.return_value['bid_date']='2026-09-10T10:30:30'

    def seed(self, name='ema', **changes):
        args=dict(strategy_id=ema_exit.STRATEGY_ID,protocol=ema_exit.PROTOCOL,state=seed())
        self.f.seed(name,**{**args,**changes})
        with self.f.connect() as conn:
            conn.execute("UPDATE shadow_candidates SET trigger_bar='2026-09-10T10:00', observed_at='2026-09-10T10:00:01' WHERE candidate_id=?",(name,))
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T10:00:03' WHERE candidate_id=?",(name,))
            if changes.get('strategy_id',ema_exit.STRATEGY_ID)==ema_exit.STRATEGY_ID:
                meta=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
                meta['strategy_version']='research.3'
                conn.execute('UPDATE shadow_candidates SET metadata_json=? WHERE candidate_id=?',(json.dumps(meta),name))

    def test_forty_overlapping_plays_price_once_and_survive_restart(self):
        for i in range(40):
            self.seed(str(i))
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' and r['decision_at']=='2026-09-10T10:30:00' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.f.capture()
        self.f.quote.assert_called_once_with('XYZ')

    def test_five_minute_strategy_and_other_account_stay_separate(self):
        self.seed(); self.seed('other',account='b')
        self.seed('reversion',strategy_id=reversion_exit.STRATEGY_ID,protocol=reversion_exit.PROTOCOL,state=reversion_seed())
        self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.f.capture()
        self.assertEqual(['ema','reversion'],[r['candidate_id'] for r in self.f.rows()])
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))

    def test_missing_matching_state_is_not_a_zero_profit(self):
        self.seed(state=None)
        self.f.capture()
        self.assertEqual(('unmeasurable','missing_exit_state'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))
        self.f.quote.assert_not_called()

    def test_native_fifteen_minute_capture_is_separate_from_legacy_and_other_strategies(self):
        import pandas as pd
        from unittest.mock import Mock
        from trading.research_ema_history import NATIVE_POLICY
        for i in range(40):
            self.seed('native'+str(i))
        self.seed('legacy')
        with self.f.connect() as conn:
            for row in conn.execute("SELECT candidate_id,metadata_json FROM shadow_candidates WHERE candidate_id LIKE 'native%'").fetchall():
                meta=json.loads(row['metadata_json']); meta['history_policy']=NATIVE_POLICY
                conn.execute('UPDATE shadow_candidates SET metadata_json=? WHERE candidate_id=?',
                             (json.dumps(meta),row['candidate_id']))
        frame=pd.DataFrame([dict(time=datetime(2026,9,10,10,15),open=100,high=101,low=97,close=100)])
        frame.attrs['source_minutes']=15
        lookup=Mock(return_value=frame)
        self.f.capture(ema_bars_lookup=lookup)
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))
        self.assertEqual(41,len(self.f.rows()))
        lookup.assert_called_once_with('META')
        self.f.quote.assert_called_once_with('XYZ')

    def test_completed_target_prices_as_2_06r_not_2r(self):
        self.seed()
        self.f.frame.loc[25,['low','high']]=[99,105]
        self.f.capture()
        self.assertEqual(('priced','underlying_2_06r_target'),
                         (self.f.rows()[0]['status'],self.f.rows()[0]['reason']))

    def test_matrix_keeps_timer_and_corrected_session_evidence_separate(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed(); self.f.capture()
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','research_strategy_ids':[ema_exit.STRATEGY_ID]},
        ),patch('scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==ema_exit.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        self.assertEqual(0,pair['option_results'])
        evidence=pair['authored_exit_evidence']
        self.assertEqual(1,evidence['option_results'])
        self.assertEqual(ema_exit.PROTOCOL,evidence['protocol'])
        self.assertEqual(-83.3,evidence['net_one_contract_pnl'])
