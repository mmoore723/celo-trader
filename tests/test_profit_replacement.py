import json
import unittest
from datetime import timedelta
from trading.trend_profit_exit import advance, PAIRS, RULE, PARTIAL, RUNNER, replacement_policy
from trading.premium_policy import fingerprint, freeze_selection, scope
from strategy_health.premium_rules import VERSION
from trading.position_manager.manage import _evaluate_reviewed_strategy_exit
from trading.position_manager.exit_preflight import full_exit_reason
from tests.test_premium_rules import T, quote

class ReplacementTests(unittest.TestCase):
    def trade(self,sid,ticker):
        policy=dict(rule=RULE,version=VERSION,account='A',mode='paper',strategy=sid,ticker=ticker,
                    strategy_version='test',approval_id='user-10-10',gain_pct=10,giveback_pct=10,replace_native_exit=True)
        policy['fingerprint']=fingerprint(policy)
        return dict(id=1,paper=True,broker_account_id='A',strategy_id=sid,ticker=ticker,
                    entry_time=T.isoformat(),strategy_context_json=json.dumps({'premium_exit_policy':policy}))
    def test_all_pairs_replace_deadlines_keep_session_safety(self):
        for sid,ticker in PAIRS:
            t=self.trade(sid,ticker)
            now=T+timedelta(minutes=100)
            self.assertEqual((False,'hold'),_evaluate_reviewed_strategy_exit(t,T,now,one_minute_bars=None,five_minute_bars=None))
            self.assertIsNone(full_exit_reason(t,{},now))
            self.assertEqual('panic',full_exit_reason(t,{'exit_pending_reason':'panic'},now))
            close=T.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).replace(hour=15,minute=55)
            self.assertEqual('research_session_close',full_exit_reason(t,{},close))
            self.assertEqual((True,'research_session_close'),_evaluate_reviewed_strategy_exit(t,T,close,one_minute_bars=None,five_minute_bars=None))
    def test_live_and_legacy_unchanged(self):
        t=self.trade('V2_SPY_TREND_CONT','SPY');t['paper']=False
        self.assertIsNone(replacement_policy(t))
        self.assertIn('markout_30m',full_exit_reason(t,{},T+timedelta(minutes=31)))
        t['paper']=True;t['strategy_context_json']='{}'
        self.assertIsNone(replacement_policy(t))
        self.assertIn('markout_30m',full_exit_reason(t,{},T+timedelta(minutes=31)))
    def test_tamper_rejected_and_entry_freeze(self):
        t=self.trade('V2_ORB_PULLBACK','TSLA');p=json.loads(t['strategy_context_json'])['premium_exit_policy']
        settings=dict(paper_trading=True,active_broker_account_id='A',premium_exit_paper_assignments={scope('A',t['strategy_id'],'TSLA','test'):p})
        frozen=freeze_selection(settings,t['strategy_id'],'TSLA','test')
        p['gain_pct']=50
        self.assertEqual(10,frozen['premium_exit_policy']['gain_pct'])
        with self.assertRaises(ValueError):freeze_selection(settings,t['strategy_id'],'TSLA','test')
    def test_ten_ten_partial_restart_and_runner(self):
        state={}
        for sec,bid,qty,sold,expected in [(1,1.09,9,0,False),(2,1.10,9,0,PARTIAL),(3,1.20,7,2,PARTIAL),(4,1.19,5,4,False),(5,1.18,5,4,RUNNER)]:
            now=T+timedelta(seconds=sec);q=quote(bid);q.update(bid_date=now.timestamp()*1000,ask_date=now.timestamp()*1000,bidsize=20)
            state,result=advance(json.loads(json.dumps(state)),entry=1,quantity=qty,sold=sold,quote=q,now=now,symbol='TEST',gain_pct=10,giveback_pct=10)
            self.assertEqual((True,expected) if expected else (False,'hold'),result)
