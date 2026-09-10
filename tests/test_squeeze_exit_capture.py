from datetime import datetime
import json
import unittest
from unittest.mock import patch

from tests import test_authored_exit_capture as fixtures
from tests.test_impulse_exit_measurement import candles
from tests.test_squeeze_exit_measurement import meta
from strategy_health import squeeze_exit as exits
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary


class SqueezeExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthoredExitCaptureTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        p=patch('database.research_premium_exits.get_conn',self.f.connect)
        p.start(); self.addCleanup(p.stop)
        self.f.frame=candles('2026-09-10T10:30',330)
        self.tick('10:32',4,'10:31:30')

    def tick(self,now,bid,stamp):
        self.f.now=datetime.fromisoformat('2026-09-10T'+now)
        self.f.quote.return_value.update(bid=bid,ask=bid+.1,bid_date='2026-09-10T'+stamp)

    def seed(self,name='one',**changes):
        self.f.seed(name,**{**dict(strategy_id=exits.STRATEGY_ID,protocol=exits.PROTOCOL,state=meta()['authored_exit_state']),**changes})
        with self.f.connect() as conn:
            raw=json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?',(name,)).fetchone()[0])
            raw.update(sma20=98,strategy_version='0.1.0')
            conn.execute("UPDATE shadow_candidates SET trigger_bar='2026-09-10T10:30',observed_at='2026-09-10T10:30:01',metadata_json=? WHERE candidate_id=?",(json.dumps(raw),name))
            conn.execute("UPDATE candidate_option_quote_observations SET observed_at='2026-09-10T10:30:03' WHERE candidate_id=?",(name,))

    def summary(self):
        with self.f.connect() as conn:
            result=authored_summary([{'candidate_id':'one'}],load_authored_exits(conn,'a','2026-09-10'),exits.PROTOCOL)
            path=conn.execute("SELECT * FROM research_premium_exit_paths WHERE candidate_id='one'").fetchone()
        return result,dict(path) if path else {}

    def test_150_percent_means_2_5_times_entry_no_orb_partial(self):
        self.seed(); self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.assertIsNone(self.summary()[1]['partial_bid'])
        self.tick('10:33',5,'10:32:30'); self.f.capture()
        self.assertEqual('premium_target_150_pct',self.f.rows()[0]['reason'])
        result,path=self.summary()
        self.assertEqual(296.7,result['net_one_contract_pnl'])
        self.assertNotIn('partial_exit_comparison',result)
        self.assertIsNone(path['partial_bid'])
        before=self.f.rows(); self.f.capture(); self.assertEqual(before,self.f.rows())

    def test_hourly_loss_and_structural_priority(self):
        self.seed(); self.f.frame.loc[59,['low','close']]=[96,97]
        self.tick('11:30:45',1,'11:30:30'); self.f.capture()
        self.assertEqual('hourly_close_below_entry_sma20',self.f.rows()[0]['reason'])
        self.assertEqual(-103.3,self.summary()[0]['net_one_contract_pnl'])

    def test_known_hourly_exit_cannot_be_overridden_by_later_target_quote(self):
        self.seed(); self.f.frame.loc[59,['low','close']]=[96,97]
        self.tick('11:30:45',6,'11:30:30'); self.f.capture()
        self.assertEqual('hourly_close_below_entry_sma20',self.f.rows()[0]['reason'])

    def test_stale_target_quote_is_ignored_and_gap_uses_actual_bid(self):
        self.seed(); self.tick('10:33',6,'10:30:30'); self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.tick('10:34',5.2,'10:33:30'); self.f.capture()
        self.assertEqual(316.7,self.summary()[0]['net_one_contract_pnl'])

    def test_missing_completed_hour_prevents_premium_win(self):
        self.seed(); self.f.frame=self.f.frame.drop(index=5)
        self.tick('11:30:45',6,'11:30:30'); self.f.capture()
        self.f.quote.assert_not_called()
        self.tick('11:36',6,'11:35:30'); self.f.capture()
        self.assertEqual('unmeasurable',self.f.rows()[0]['status'])

    def test_all_40_overlaps_and_account_isolation(self):
        for i in range(40): self.seed(str(i))
        self.seed('other',account='b'); self.seed('wrong',strategy_id='V2_ORB_PULLBACK')
        self.tick('10:32',5,'10:31:30'); self.f.capture()
        self.assertEqual(40,len(self.f.rows()))
        self.assertTrue(all(r['status']=='priced' for r in self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')

    def test_original_cap_one_minute_quote_window_and_failure_recovery(self):
        self.seed(); self.tick('15:55:45',1,'15:55:30')
        self.f.quote.side_effect=RuntimeError('offline'); self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.quote.side_effect=None; self.f.capture()
        self.assertEqual('eod_1555_cap',self.f.rows()[0]['reason'])
        self.assertEqual('priced',self.f.rows()[0]['status'])

    def test_slow_exit_quote_and_wrong_contract_cannot_be_priced(self):
        self.seed(); self.f.quote.return_value['symbol']='WRONG'
        self.tick('10:32',5,'10:31:30'); self.f.capture()
        self.assertEqual('collecting',self.f.rows()[0]['status'])
        self.f.quote.return_value['symbol']='XYZ'
        self.tick('15:55:45',1,'15:55:30'); quote=self.f.quote.return_value
        def slow(_):
            self.f.now=datetime(2026,9,10,15,56,1)
            return quote
        self.f.quote.side_effect=slow; self.f.capture()
        self.assertEqual('pending_quote',self.f.rows()[0]['status'])
        self.f.capture(); self.assertEqual('missing_quote',self.f.rows()[0]['status'])

    def test_matrix_has_single_contract_evidence(self):
        self.seed(); self.tick('10:32',5,'10:31:30'); self.f.capture()
        from strategy_health.research_matrix import build_research_matrix
        with patch('database.get_conn',self.f.connect),patch('database._now_et',return_value=self.f.now),patch(
            'config.get_settings',return_value={'active_broker_account_id':'a','observe_ctx_squeeze_macd_enabled':True}),patch(
            'scanner.state_io._read_daily_universe',return_value={}):
            matrix=build_research_matrix()
        strategy=next(s for s in matrix['strategies'] if s['strategy_id']==exits.STRATEGY_ID)
        pair=next(p for p in strategy['pairs'] if p['ticker']=='META')
        self.assertEqual(1,pair['authored_exit_evidence']['option_results'])
        self.assertNotIn('partial_exit_comparison',pair['authored_exit_evidence'])
