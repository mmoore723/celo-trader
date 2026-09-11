from datetime import datetime
import json
import unittest
from unittest.mock import patch

from strategy_health import context_orb_exit as module
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary
from tests import test_authored_exit_capture as fixtures
from tests.test_context_orb_exit_measurement import meta
from tests.test_impulse_exit_measurement import candles
from trading.context_research_entries import evidence_version


class ContextOrbExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        patcher=patch('database.research_premium_exits.get_conn',self.f.connect)
        patcher.start(); self.addCleanup(patcher.stop)
        self.f.frame=candles('2026-09-10T10:05',350)
        self.tick('10:07',2.6,'10:06:30')

    def tick(self,now,bid,stamp):
        self.f.now=datetime.fromisoformat('2026-09-10T'+now)
        self.f.quote.return_value=dict(symbol='XYZ',source_symbol='XYZ',bid=bid,ask=bid+.1,
                                      bid_date='2026-09-10T'+stamp)

    def seed(self,name='one',**changes):
        args=dict(strategy_id=module.STRATEGY_ID,protocol=module.PROTOCOL,state=meta()['authored_exit_state'])
        self.f.seed(name,**{**args,**changes})
        with self.f.connect() as conn:
            saved=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
            saved.update(or_midpoint=98,strategy_version=evidence_version(args['strategy_id'],'0.1.0'))
            conn.execute('UPDATE shadow_candidates SET metadata_json=? WHERE candidate_id=?',(json.dumps(saved),name))

    def summary(self):
        with self.f.connect() as conn:
            exits=load_authored_exits(conn,'a','2026-09-10')
        return authored_summary([{'candidate_id':'one'}],exits,module.PROTOCOL)

    def test_partial_then_runner_accounting_and_restart(self):
        self.seed(); self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.assertEqual(0,self.summary()['option_results'])
        self.tick('10:08',4,'10:07:30'); self.f.capture()
        result=self.summary()
        self.assertEqual(196.7,result['net_one_contract_pnl'])
        self.assertEqual(253.4,result['partial_exit_comparison']['net_two_contract_pnl'])
        self.assertEqual(1,result['partial_exit_comparison']['partial_sales'])
        before=self.f.rows(); self.f.capture()
        self.assertEqual(before,self.f.rows()); self.assertEqual(2,self.f.quote.call_count)
        from database.schema import _init_db_at
        _init_db_at(self.f.path)
        self.assertEqual(result,self.summary())

    def test_gap_straight_to_double_prices_both_whole_contracts_at_real_bid(self):
        self.seed(); self.tick('10:07',4.2,'10:06:30'); self.f.capture()
        result=self.summary()
        self.assertEqual(216.7,result['net_one_contract_pnl'])
        self.assertEqual(433.4,result['partial_exit_comparison']['net_two_contract_pnl'])

    def test_midpoint_exit_has_priority_over_target_at_exit_quote(self):
        self.seed(); self.f.frame.loc[1,['low','close']]=[96,97]
        self.tick('10:07:45',4,'10:07:30'); self.f.capture()
        self.assertEqual('or_midpoint_close',self.f.rows()[0]['reason'])
        self.assertEqual(0,self.summary()['partial_exit_comparison']['partial_sales'])

    def test_structural_quote_deadline_is_one_minute_not_five(self):
        self.seed(); self.f.frame.loc[1,['low','close']]=[96,97]
        self.tick('10:08:01',4,'10:08'); self.f.capture()
        self.assertEqual('missing_quote',self.f.rows()[0]['status'])
        self.f.quote.assert_not_called()

    def test_gaps_and_wrong_contract_never_get_profit_credit(self):
        self.seed(); self.f.frame=self.f.frame.drop(index=1)
        self.f.capture(); self.f.quote.assert_not_called()
        self.f.frame=candles('2026-09-10T10:05',350)
        self.f.quote.return_value['symbol']='WRONG'; self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.assertEqual(0,self.summary()['option_results'])

    def test_all_overlapping_candidates_share_quote_and_keep_accounts_separate(self):
        for i in range(40): self.seed(str(i))
        self.seed('other',account='b'); self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.tick('10:07',4,'10:06:30'); self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')

    def test_late_entry_and_missing_state_unmeasurable(self):
        self.seed(state=None); self.seed('late')
        with self.f.connect() as conn:
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T10:06' WHERE candidate_id='late'")
        self.f.capture()
        self.assertEqual(['late_entry_quote','missing_exit_state'],[r['reason'] for r in self.f.rows()])
        self.f.quote.assert_not_called()

    def test_matrix_exposes_separate_one_and_two_contract_results(self):
        self.seed(); self.tick('10:07',4,'10:06:30'); self.f.capture()
        from strategy_health.research_matrix import build_research_matrix
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','observe_ctx_orb_nr7_inside_enabled':True}),patch(
            'scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==module.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertEqual(1,pair['option_results'])
        self.assertEqual(196.7,pair['net_one_contract_pnl'])
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
        self.assertEqual(393.4,pair['authored_exit_evidence']['partial_exit_comparison']['net_two_contract_pnl'])

    def test_partial_then_losing_runner_does_not_hide_loss(self):
        self.seed(); self.f.capture()
        self.f.frame.loc[2,['low','close']]=[96,97]
        self.tick('10:08:45',1,'10:08:30'); self.f.capture()
        result=self.summary()
        self.assertEqual(-103.3,result['net_one_contract_pnl'])
        self.assertEqual(-46.6,result['partial_exit_comparison']['net_two_contract_pnl'])
        self.assertEqual(0,result['partial_exit_comparison']['profit_factor'])

    def test_no_partial_if_target_not_observed_and_stale_quote_rejected(self):
        self.seed(); self.tick('10:07',4,'10:05:30'); self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.f.frame.loc[2,['low','close']]=[96,97]
        self.tick('10:08:45',1,'10:08:30'); self.f.capture()
        self.assertEqual(-206.6,self.summary()['partial_exit_comparison']['net_two_contract_pnl'])
        self.assertEqual(0,self.summary()['partial_exit_comparison']['partial_sales'])

    def test_original_session_close_and_quote_recovery(self):
        self.seed(); self.tick('15:55:30',1,'15:55:10')
        self.f.quote.side_effect=RuntimeError('quote offline'); self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.quote.side_effect=None; self.f.capture()
        self.assertEqual('priced',self.f.rows()[0]['status'])
        self.assertEqual('eod_1555_cap',self.f.rows()[0]['reason'])

    def test_slow_quote_request_cannot_extend_structural_deadline(self):
        self.seed(); self.f.frame.loc[1,['low','close']]=[96,97]
        self.tick('10:07:45',1,'10:07:30')
        quote=self.f.quote.return_value
        def slow(_):
            self.f.now=datetime(2026,9,10,10,8,30)
            return quote
        self.f.quote.side_effect=slow
        self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.capture()
        self.assertEqual('missing_quote',self.f.rows()[0]['status'])
