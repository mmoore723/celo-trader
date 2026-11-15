import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch
from config import engine_parameters as ep
from config import execution_parameters as xp
from config.strategy_catalog import REVIEWED_STRATEGIES

class ExecutionConfigurationTests(unittest.TestCase):
    def settings(self,sid='V2_ORB_PULLBACK',ticker='TSLA',execution=None):
        s={'paper_trading':True,'active_broker_account_id':'test'}
        v=REVIEWED_STRATEGIES[sid].version
        view=ep.describe(s,sid,ticker,v)
        return {**s,**ep.save(s,sid,ticker,v,view['revision'],{},'test',execution=execution or {})}
    def trade(self,sid='V2_ORB_PULLBACK',ticker='TSLA',execution=None):
        return dict(strategy_id=sid,ticker=ticker,strategy_context_json=xp.freeze(self.settings(sid,ticker,execution),sid,ticker))
    def test_inventory_reads_without_mutating_settings(self):
        for sid,rule in REVIEWED_STRATEGIES.items():
            from config.research_order_specs import SPECS
            allowed=SPECS[sid].allowed_tickers if sid in SPECS else rule.tickers
            ticker=next(iter(allowed or rule.tickers),'SPY');s={'paper_trading':True};before=deepcopy(s)
            d=ep.describe(s,sid,ticker,rule.version)
            self.assertIn('minimum_dte',d['execution']['contract'])
            self.assertEqual(before,s)
    def test_custom_timer_survives_serialization_old_trade_unchanged(self):
        from trading.v2_orb_paper_exit import evaluate_v2_orb_paper_exit
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00')
        trade=self.trade(execution={'native_exit':{'hold_minutes':45}})
        trade=json.loads(json.dumps(trade))
        with xp.from_trade(trade):
            self.assertFalse(evaluate_v2_orb_paper_exit(at,at+timedelta(minutes=44))[0])
            self.assertTrue(evaluate_v2_orb_paper_exit(at,at+timedelta(minutes=45))[0])
        self.assertFalse(evaluate_v2_orb_paper_exit(at,at+timedelta(minutes=45))[0])
        with xp.from_trade({'strategy_id':'V2_ORB_PULLBACK','ticker':'TSLA'}):
            self.assertFalse(evaluate_v2_orb_paper_exit(at,at+timedelta(minutes=45))[0])
    def test_preflight_uses_frozen_timer_without_quote(self):
        from trading.position_manager.exit_preflight import full_exit_reason
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00')
        t=self.trade(execution={'native_exit':{'hold_minutes':45}});t['entry_time']=at.isoformat()
        self.assertIn('45m',full_exit_reason(t,{},at+timedelta(minutes=46)))
    def test_account_ticker_mode_isolation_and_validation(self):
        s=self.settings(execution={'contract':{'minimum_dte':9}})
        self.assertEqual(9,xp.saved(s,'V2_ORB_PULLBACK','TSLA')['contract']['minimum_dte'])
        for changed in ({'paper_trading':False},{'active_broker_account_id':'other'}):self.assertEqual({},xp.saved({**s,**changed},'V2_ORB_PULLBACK','TSLA'))
        self.assertEqual({},xp.saved(s,'V2_ORB_PULLBACK','SPY'))
        for invalid in ({'contract':{'minimum_dte':30,'maximum_dte':10}},{'contract':{'minimum_premium':float('nan')}},{'native_exit':{'hold_minutes':False}},{'native_exit':{'structural_stop_enabled':False}}):
            with self.assertRaises(ValueError):self.settings(execution=invalid)
    def test_tampered_or_wrong_pair_frozen_controls_rejected(self):
        t=self.trade(execution={'native_exit':{'hold_minutes':45}})
        t['ticker']='SPY'
        with self.assertRaises(ValueError):
            with xp.from_trade(t):pass
    def test_contract_selector_uses_custom_window_price_and_ranking(self):
        from trading.entry.contract import select_reviewed_v2_contract
        from tests.test_research_contract_selection import _Tradier
        at=datetime(2026,9,1,10)
        reader=_Tradier(['2026-09-04'],{'2026-09-04':[{'symbol':'cheap','strike':101,'bid':.94,'ask':1.0},{'symbol':'near','strike':100.5,'bid':1.44,'ask':1.5},{'symbol':'crossed','strike':100.1,'bid':1.1,'ask':.9}]})
        s=self.settings(execution={'contract':{'minimum_open_interest':0,'maximum_spread_dollars':0,'minimum_dte':0,'maximum_dte':4,'minimum_premium':.5,'maximum_premium':2,'primary_policy':'lowest_ask_150_1000'}})
        with patch('trading.entry.contract.get_settings',return_value=s),patch('trading.research_contract_selection._now_et',return_value=at):
            c,detail=select_reviewed_v2_contract(reader,'TSLA','bullish',100,500,strategy_id='V2_ORB_PULLBACK')
        self.assertEqual('cheap',c['symbol']);self.assertEqual(0,reader.expiration_kwargs['minimum_dte']);self.assertEqual(4,reader.expiration_kwargs['maximum_dte']);self.assertEqual(1,detail['screen_counts']['invalid_price'])
    def test_contract_change_cannot_restore_replaced_timer(self):
        from tests.test_engine_parameters import ProfitConfigurationTests
        s,v=ProfitConfigurationTests().settings();sid='V2_SPY_TREND_CONT';view=ep.describe(s,sid,'SPY',v)
        self.assertEqual({},view['execution']['native_exit'])
        with self.assertRaises(ValueError):ep.save(s,sid,'SPY',v,view['revision'],{},'test',execution={'native_exit':{'hold_minutes':45}})
        update=ep.save(s,sid,'SPY',v,view['revision'],{},'test',execution={'contract':{'maximum_dte':30}})
        self.assertEqual({},xp.saved({**s,**update},sid,'SPY').get('native_exit',{}))
    def test_deadline_matches_frozen_timer(self):
        from trading.entry.exit_deadline import freeze_at_fill
        t=self.trade(execution={'native_exit':{'hold_minutes':45}})
        c=t['strategy_context_json'];c['exit_deadline_capture']={'status':'awaiting_fill','hold_minutes':90,'session_cap':'2026-11-13T15:55:00-05:00'}
        result=freeze_at_fill(c,'2026-11-13T10:00:00-05:00')
        self.assertEqual('2026-11-13T10:45:00-05:00',result['exit_deadline'])
    def test_saved_execution_preserved_by_older_clients(self):
        s=self.settings(execution={'native_exit':{'hold_minutes':45}});sid='V2_ORB_PULLBACK';v=REVIEWED_STRATEGIES[sid].version;view=ep.describe(s,sid,'TSLA',v)
        update=ep.save(s,sid,'TSLA',v,view['revision'],{},'test')
        self.assertEqual(45,xp.saved({**s,**update},sid,'TSLA')['native_exit']['hold_minutes'])
    def test_structural_bar_cap_changes_only_frozen_trade(self):
        import pandas as pd
        from strategy_health.impulse_exit import first_exit
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00')
        frame=pd.DataFrame([dict(time=at+timedelta(minutes=i),open=100,high=101,low=99,close=100) for i in range(10)])
        args=dict(entry_at=at,entry_quote_at=at,stop=90,target=110,direction='bullish',now=at+timedelta(minutes=10))
        self.assertIsNone(first_exit(frame,**args))
        t=self.trade('V2_IMPULSE_ANCHORED_VWAP_PULLBACK','NVDA',{'native_exit':{'max_hold_bars':1}})
        with xp.from_trade(t):self.assertEqual('configured_time_cap_5m',first_exit(frame,**args)[1])
        self.assertIsNone(first_exit(frame,**args))
    def test_context_partial_threshold_is_used_by_execution(self):
        from config.research_order_specs import SPECS
        from trading.research_order_exit import evaluate_exit
        import pandas as pd
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00');now=at+timedelta(minutes=10)
        sid='RESEARCH_CTX_ORB_ATR10_V2';t=self.trade(sid,'SPY',{'native_exit':{'partial_gain_pct':15,'final_gain_pct':50}})
        t.update(entry_price=2,contract_symbol='OPTION',contracts=4)
        t['strategy_context_json'].update(strategy_version=SPECS[sid].version,research_order_route='exact_research_v1')
        q=dict(symbol='OPTION',source_symbol='OPTION',bid=2.4,ask=2.45,bid_date=now.isoformat())
        with patch('strategy_health.context_orb_exit.first_exit',return_value=None),patch('trading.research_order_exit.partial_remaining',return_value=2):
            self.assertEqual((True,'stage1_research_atr10'),evaluate_exit(t,at,now,pd.DataFrame([{'time':at}]),q))
            t['strategy_context_json'].pop('execution_controls')
            self.assertEqual((False,'hold'),evaluate_exit(t,at,now,pd.DataFrame([{'time':at}]),q))
    def test_native_giveback_threshold_and_pending_survive_restart(self):
        from trading.tsla_giveback_exit import giveback_exit
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00')
        t=self.trade('V2_TSLA_TWO_LEG_TREND_PULLBACK','TSLA',{'native_exit':{'legacy_arm_dollars':40.,'legacy_giveback_pct':20.}})
        with xp.from_trade(t):
            state={};self.assertFalse(giveback_exit(state,2,2.4,at)[0])
            state=json.loads(json.dumps(state))
            self.assertEqual((True,'tsla_giveback_40_20'),giveback_exit(state,2,2.3,at+timedelta(minutes=1)))
            self.assertTrue(giveback_exit(json.loads(json.dumps(state)),2,None,at+timedelta(minutes=2))[0])
        self.assertFalse(giveback_exit({},2,2.4,at)[0])
