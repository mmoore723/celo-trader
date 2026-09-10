from datetime import datetime
import json
import unittest
from unittest.mock import patch

from tests import test_authored_exit_capture as fixtures
from tests.test_context_vwap_exit import meta, session
from strategy_health import context_vwap_exit as exits
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary


class ContextVwapCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.frame=session(); self.f.frame.loc[36,'high']=104
        self.f.now=datetime(2026,9,10,10,7,45)
        self.f.quote.return_value.update(bid_date='2026-09-10T10:07:30')

    def seed(self,name='one',**changes):
        self.f.seed(name,**{**dict(strategy_id=exits.STRATEGY_ID,protocol=exits.PROTOCOL,
                                  state=meta()['authored_exit_state']),**changes})
        with self.f.connect() as conn:
            data=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
            data.update(previous_high=104,strategy_version='0.1.0')
            conn.execute('UPDATE shadow_candidates SET metadata_json=? WHERE candidate_id=?',(json.dumps(data),name))

    def test_actual_quote_and_costs_are_separate_from_timer_results(self):
        self.seed(); self.f.capture()
        row=self.f.rows()[0]
        self.assertEqual(('priced','prior_high_target',1.2),(row['status'],row['reason'],row['bid']))
        with self.f.connect() as conn:
            result=authored_summary([{'candidate_id':'one'}],load_authored_exits(conn,'a','2026-09-10'),exits.PROTOCOL)
        self.assertEqual(-83.3,result['net_one_contract_pnl'])
        self.assertEqual(0,result['profit_factor'])
        self.f.capture(); self.assertEqual([row],self.f.rows()); self.f.quote.assert_called_once()

    def test_all_overlaps_share_quote_and_exclude_other_account(self):
        for i in range(40): self.seed(str(i))
        self.seed('other',account='b'); self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')

    def test_missing_source_or_session_history_cannot_be_priced(self):
        self.seed(); self.seed('bad',state=None)
        self.f.frame=self.f.frame.drop(index=0); self.f.capture()
        self.assertEqual(['missing_exit_state','missing_bars'],[r['reason'] for r in self.f.rows()])
        self.f.quote.assert_not_called()

    def test_one_minute_quote_deadline_including_slow_network(self):
        self.seed(); quote=self.f.quote.return_value
        def slow(_):
            self.f.now=datetime(2026,9,10,10,8,1)
            return quote
        self.f.quote.side_effect=slow; self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.capture(); self.assertEqual('missing_quote',self.f.rows()[0]['status'])

    def test_wrong_contract_and_quote_failure_recovery(self):
        self.seed(); self.f.quote.return_value['symbol']='WRONG'; self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.quote.return_value['symbol']='XYZ'
        self.f.quote.side_effect=RuntimeError('offline'); self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.quote.side_effect=None; self.f.capture()
        self.assertEqual('priced',self.f.rows()[0]['status'])

    def test_matrix_exposes_exact_current_ker_protocol(self):
        self.seed(); self.f.capture()
        from strategy_health.research_matrix import build_research_matrix
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','observe_ctx_vwap_ker_enabled':True}),patch(
            'scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==exits.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertEqual(exits.PROTOCOL,pair['authored_exit_evidence']['protocol'])
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
