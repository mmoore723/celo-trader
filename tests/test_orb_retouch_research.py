import unittest
from unittest.mock import Mock, patch
from copy import deepcopy
import pandas as pd
from trading import orb_retouch_research as research
from trading import orb_retouch_execution as source
from trading.entry.injected_setups import evaluate_injected_setups, ORB
from tests.test_orb_retouch_execution import frame
from tests import test_option_profit_protection as fixtures


def bars(extra=(101.,)):
    return frame([100.]*15+list(extra),[100.5]*15+[max(c,100.5)+.2 for c in extra],
                 [99.5]*15+[min(c,100.5)-.2 for c in extra])


def quote(now,price=100.53):
    return dict(ap=price+.01,bp=price-.01,t=pd.Timestamp(now,tz='America/New_York').isoformat())


class RetouchResearchTests(unittest.TestCase):
    def run_entry(self,state,frame,now='2026-01-02 09:47:12',price=100.53,**kwargs):
        return research.update(state,frame,ticker='META',now=now,scope='research_worker:a',quote=quote(now,price),**kwargs)

    def test_first_quote_and_levels_match_native_but_only_emit_once(self):
        data=bars();state={};now=pd.Timestamp('2026-01-02 09:47:12')
        old,_=source.update_one_minute_orb_retouch({},data,ticker='TSLA',quote_price=100.53,now=now)
        signal,status=self.run_entry(state,data)
        self.assertEqual('first_retouch_quote',status)
        for key in ('v2_entry_reference','v2_stop','v2_target','or_high','or_low','entry_timing','retest_level'):
            self.assertAlmostEqual(old.meta[key],signal.meta[key]) if isinstance(old.meta[key],float) else self.assertEqual(old.meta[key],signal.meta[key])
        self.assertEqual(now.tz_localize('America/New_York'),signal.trigger_bar)
        self.assertIsNone(self.run_entry(state,data)[0])

    def test_each_new_close_inside_then_break_can_overlap_earlier_play(self):
        state={};first,_=self.run_entry(state,bars())
        second,_=self.run_entry(state,bars((101.,100.5,101.)),now='2026-01-02 09:48:12')
        self.assertIsNotNone(second)
        self.assertNotEqual(first.meta['research_play_key'],second.meta['research_play_key'])
        self.assertNotEqual(first.meta['research_episode_anchor'],second.meta['research_episode_anchor'])
        self.assertIsNone(self.run_entry(state,bars((101.,101.,101.)),now='2026-01-02 09:48:12')[0])

    def test_failed_quote_and_short_break_do_not_lock_out_new_long(self):
        state={};self.assertIsNone(self.run_entry(state,bars(),price=100.40)[0])
        self.assertIsNone(self.run_entry(state,bars())[0])
        self.assertIsNotNone(self.run_entry(state,bars((101.,100.,101.)),now='2026-01-02 09:48:12')[0])
        state={};self.assertIsNone(self.run_entry(state,bars((99.,)),price=99.5)[0])
        self.assertIsNotNone(self.run_entry(state,bars((99.,100.,101.)),now='2026-01-02 09:48:12')[0])

    def test_completed_failure_is_not_repriced_as_delayed_retouch(self):
        self.assertIsNone(self.run_entry({},bars((101.,100.)))[0])

    def test_timestamped_quote_after_breakout_is_required(self):
        now=pd.Timestamp('2026-01-02 09:47:12')
        for change in ({'t':None},{'t':'2026-01-02T09:45:59-05:00'},{'t':'2026-01-02T09:47:13-05:00'},
                       {'t':'2026-01-02T09:47:12'},{'ap':100.},{'bp':float('nan')}):
            q=quote(now);q.update(change)
            self.assertIsNone(research.update({},bars(),ticker='META',quote=q,now=now,scope='research_worker:a')[0])
        for stamp in ('2026-01-02 09:45:20','2026-01-02 10:31','2026-01-03 09:47:12'):
            self.assertIsNone(self.run_entry({},bars(),now=stamp)[0])

    def test_worker_only_injection_and_scope_isolation(self):
        now=pd.Timestamp('2026-01-02 09:47:12');data=bars();keys=set()
        for scope,ticker in [('research_worker:a','META'),('research_worker:b','META'),('research_worker:a','NVS')]:
            s,_=research.update({},data,ticker=ticker,scope=scope,now=now,quote=quote(now))
            keys.add(s.meta['research_play_key'])
        self.assertEqual(3,len(keys))
        with patch('trading.entry.injected_setups._now_et',return_value=now),patch('trading.entry.injected_setups.record_underlying_quote'):
            signals,_,_=evaluate_injected_setups({},data,'META',set(),{ORB},Mock(get_latest_quote=Mock(return_value=quote(now))),{},research_scope='research_worker:a')
            self.assertEqual(1,len(signals));self.assertTrue(signals[0].meta['observation_only'])
            with self.assertRaises(ValueError):
                evaluate_injected_setups({},data,'TSLA',{ORB},set(),Mock(),{},research_scope='research_worker:a')
        from config.strategy_catalog import reviewed_strategy_integrity_errors
        self.assertEqual({},reviewed_strategy_integrity_errors())


class DurableRetouchTests(unittest.TestCase):
    setUp=fixtures.CaptureTests.setUp
    connect=fixtures.CaptureTests.connect

    def test_restart_keeps_original_candidate_and_never_reselects_contract(self):
        from shadow_ledger import record_router_candidate
        from trading.entry.candidate_observation import observe_candidate_contract
        now=pd.Timestamp('2026-01-02 09:47:12')
        def signal():
            return research.update({},bars(),ticker='META',quote=quote(now),now=now,scope='research_worker:a')[0]
        one,two=signal(),signal()  # Two independent worker states, as on restart.
        with patch('shadow_ledger.get_conn',self.connect),patch('config.get_settings',return_value={'active_broker_account_id':'a'}):
            record_router_candidate('META',one,100.53)
            with self.connect() as conn:
                before=dict(conn.execute('SELECT * FROM shadow_candidates').fetchone())
            with patch('trading.entry.reference_contract_observation.observe') as reference:
                observe_candidate_contract(ticker='META',signal=two,underlying_price=100.54,
                    tradier=Mock(),balance=5000,risk=Mock(),settings={},research_only=True)
                reference.assert_not_called()
            self.assertTrue(two.meta['research_existing_candidate'])
            self.assertEqual(one.meta['shadow_candidate_id'],two.meta['shadow_candidate_id'])
            with self.connect() as conn:
                rows=conn.execute('SELECT * FROM shadow_candidates').fetchall()
                self.assertEqual(1,len(rows));self.assertEqual(before,dict(rows[0]))

    def test_native_candidates_keep_independent_identity(self):
        from shadow_ledger import record_router_candidate
        now=pd.Timestamp('2026-01-02 09:47:12')
        signal,_=source.update_one_minute_orb_retouch({},bars(),ticker='TSLA',quote_price=100.53,now=now)
        second=deepcopy(signal)
        with patch('shadow_ledger.get_conn',self.connect),patch('config.get_settings',return_value={}):
            record_router_candidate('TSLA',signal,100.53);record_router_candidate('TSLA',second,100.53)
        self.assertNotEqual(signal.meta['shadow_candidate_id'],second.meta['shadow_candidate_id'])
