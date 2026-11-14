import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from config.engine_parameters import *
from config.strategy_catalog import REVIEWED_STRATEGIES

class EngineParameterTests(unittest.TestCase):
    def setUp(self):
        self.sid='V2_SPY_TREND_CONT';self.version=REVIEWED_STRATEGIES[self.sid].version
        self.settings={'paper_trading':True,'active_broker_account_id':'test-paper'}
    def saved(self,settings=None,ticker='SPY',entry=None):
        settings=settings or self.settings
        view=describe(settings,self.sid,ticker,self.version)
        return {**settings,**save(settings,self.sid,ticker,self.version,view['revision'],entry or {'fast_ema':7},'test')}
    def test_defaults_are_exact_and_persist_no_other_settings(self):
        from strategies.market_structure import TrendContinuationConfig
        before=deepcopy(self.settings)
        with for_pair(self.settings,self.sid,'SPY'):
            self.assertEqual(TrendContinuationConfig(),configured(TrendContinuationConfig()))
        updated=self.saved()
        self.assertEqual(before,self.settings)
        self.assertEqual(set(updated)-set(before),{KEY})
        with for_pair(updated,self.sid,'SPY'):
            self.assertEqual(7,configured(TrendContinuationConfig()).fast_ema)
            self.assertEqual(20,configured(TrendContinuationConfig()).slow_ema)
    def test_scope_isolation_and_exception_reset(self):
        saved=self.saved()
        for s,t in [(saved,'QQQ'),({**saved,'paper_trading':False},'SPY'),({**saved,'active_broker_account_id':'other'},'SPY')]:
            with for_pair(s,self.sid,t): self.assertEqual(10,parameter('fast_ema',10))
        with self.assertRaises(RuntimeError):
            with for_pair(saved,self.sid,'SPY'):raise RuntimeError('test')
        self.assertEqual(10,parameter('fast_ema',10))
        def read(value):
            s=self.saved(entry={'fast_ema':value})
            with for_pair(s,self.sid,'SPY'):return parameter('fast_ema',10)
        with ThreadPoolExecutor(2) as pool:self.assertEqual([5,8],list(pool.map(read,[5,8])))
    def test_validation_and_conflicts(self):
        view=describe(self.settings,self.sid,'SPY',self.version)
        for entry in [{'fast_ema':float('nan')},{'fast_ema':20},{'slow_ema':1},{'unknown':1},{'fast_ema':True}]:
            with self.assertRaises(ValueError):save(self.settings,self.sid,'SPY',self.version,view['revision'],entry,'test')
        with self.assertRaises(RuntimeError):save(self.saved(),self.sid,'SPY',self.version,view['revision'],{'fast_ema':8},'test')
    def test_library_engine_consumes_saved_configuration(self):
        from config.research_order_specs import SPECS
        from trading.tested_strategy_research import strategy_details
        sid='V2_VWAP_PULLBACK';v=REVIEWED_STRATEGIES[sid].version
        view=describe(self.settings,sid,'AMZN',v)
        s={**self.settings,**save(self.settings,sid,'AMZN',v,view['revision'],{'fast_ema':5},'test')}
        lib=strategy_details(SPECS[sid].source)
        with for_pair(s,sid,'AMZN'):self.assertEqual(5,configure_engine(lib.factory()).config.fast_ema)
        self.assertNotEqual(5,lib.factory().config.fast_ema)

class ProfitConfigurationTests(unittest.TestCase):
    def settings(self):
        import json
        from tests.test_profit_replacement import ReplacementTests
        from trading.premium_policy import scope,fingerprint
        policy=json.loads(ReplacementTests().trade('V2_SPY_TREND_CONT','SPY')['strategy_context_json'])['premium_exit_policy']
        version=REVIEWED_STRATEGIES['V2_SPY_TREND_CONT'].version
        policy['strategy_version']=version;policy['fingerprint']=fingerprint(policy)
        return {'paper_trading':True,'active_broker_account_id':'A','premium_exit_paper_assignments':{scope('A','V2_SPY_TREND_CONT','SPY',version):policy}},version
    def test_new_entry_thresholds_and_old_position_unchanged(self):
        from trading.premium_policy import freeze_selection
        from trading.trend_profit_exit import replacement_policy,advance
        from tests.test_adverse_candle_exit import T,quote
        s,v=self.settings();before=deepcopy(s);sid='V2_SPY_TREND_CONT'
        old=freeze_selection(s,sid,'SPY',v)
        view=describe(s,sid,'SPY',v)
        profit={'gain_pct':15,'giveback_pct':20,'adverse_candle_failsafe':{'timeframe_minutes':5,'consecutive_candles':2,'loss_pct':20}}
        update=save(s,sid,'SPY',v,view['revision'],{},'test',profit=profit)
        new=freeze_selection({**s,**update},sid,'SPY',v)['premium_exit_policy']
        self.assertEqual(before,s);self.assertEqual(10,old['premium_exit_policy']['gain_pct']);self.assertEqual(15,new['gain_pct'])
        self.assertEqual(new,replacement_policy(dict(paper=True,broker_account_id='A',strategy_id=sid,ticker='SPY',strategy_context_json={'premium_exit_policy':new})))
        state,decision=advance({},entry=2,quantity=4,sold=0,quote=quote(2.2,T),now=T,symbol='TEST',gain_pct=new['gain_pct'],giveback_pct=new['giveback_pct'])
        self.assertFalse(decision[0])
        self.assertEqual({},freeze_selection({**s,**update,'paper_trading':False},sid,'SPY',v))
    def test_changed_fail_safe_uses_threshold_and_remains_sticky(self):
        from trading.adverse_candle_exit import apply,is_failsafe_reason
        from tests.test_adverse_candle_exit import T,quote,frame
        from datetime import timedelta
        t=dict(entry_time=T.isoformat(),entry_price=2,contract_symbol='TEST',option_type='call')
        at=T+timedelta(minutes=10);spec={'timeframe_minutes':5,'consecutive_candles':2,'loss_pct':20}
        self.assertIsNone(apply({},trade=t,quantity=4,sold=0,quote=quote(1.7,at),now=at,frame=frame(),spec=spec)[1])
        state,d=apply({},trade=t,quantity=4,sold=0,quote=quote(1.6,at),now=at,frame=frame(),spec=spec)
        self.assertEqual((True,'adverse_2x5m_20pct_loss'),d);self.assertTrue(is_failsafe_reason(d[1]))
        self.assertEqual(d,apply(state,trade=t,quantity=4,sold=0,quote=None,now=at,frame=None,spec=spec)[1])
    def test_pair_sizing_and_restore(self):
        from config.engine_parameters import entry_cycle,select_sizing,sizing_settings
        from auth.context import get_current_user_id
        s,v=self.settings();sid='V2_SPY_TREND_CONT';view=describe(s,sid,'SPY',v)
        updated={**s,**save(s,sid,'SPY',v,view['revision'],{},'test',risk={'risk_per_trade':.02,'max_position_dollars_pct':8})}
        @entry_cycle
        def check():
            select_sizing(updated,sid,'SPY')
            self.assertEqual(.02,sizing_settings(s,get_current_user_id())['risk_per_trade'])
            self.assertNotIn('risk_per_trade',sizing_settings(s,'other'))
        check();self.assertNotIn('risk_per_trade',sizing_settings(s,get_current_user_id()))
    def test_all_catalog_routes_have_real_declared_inputs(self):
        for sid in REVIEWED_STRATEGIES:self.assertTrue(definition(sid),sid)
    def test_frozen_configured_library_exit_keeps_stop_and_survives_json(self):
        import json
        from research.engine.strategies.vwap_pullback import VWAPPullback,VWAPPullbackConfig
        from strategy_health import vwap_exit
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo
        engine=VWAPPullback(VWAPPullbackConfig(fast_ema=5));engine._configuration_revision='explicit-save'
        seed=json.loads(json.dumps(vwap_exit.entry_state(engine)))
        at=datetime(2026,11,13,10,tzinfo=ZoneInfo('America/New_York'))
        with patch.object(vwap_exit,'structural_exit',return_value=(at,'underlying_stop')) as evaluate:
            self.assertEqual((at,'underlying_stop'),vwap_exit.first_exit(None,seed=seed,entry_at=at,stop=100))
            self.assertEqual(100,evaluate.call_args.kwargs['stop'])
            seed['config']['fast_ema']=6
            self.assertEqual('missing_exit_state',vwap_exit.first_exit(None,seed=seed,entry_at=at)[1])
    def test_previous_context_fingerprint_only_accepts_identical_exit_state(self):
        from strategy_health.context_orb_exit import compatible_state,PREVIOUS_ENTRY_HASH,metadata,STRATEGY_ID
        expected=metadata(STRATEGY_ID)['authored_exit_state']
        self.assertTrue(compatible_state({**expected,'engine_hash':PREVIOUS_ENTRY_HASH},expected))
        self.assertFalse(compatible_state({**expected,'engine_hash':'unreviewed'},expected))
        self.assertFalse(compatible_state({**expected,'engine_hash':PREVIOUS_ENTRY_HASH,'policy':'changed'},expected))
    def test_changed_assignment_can_be_reviewed_without_silently_using_old_override(self):
        from trading.premium_policy import freeze_selection,fingerprint
        s,v=self.settings();sid='V2_SPY_TREND_CONT';view=describe(s,sid,'SPY',v)
        profit={'gain_pct':15,'giveback_pct':20,'adverse_candle_failsafe':None}
        s.update(save(s,sid,'SPY',v,view['revision'],{},'test',profit=profit))
        assignment=next(iter(s['premium_exit_paper_assignments'].values()))
        assignment['gain_pct']=12;assignment['configuration_editor']=1;assignment['fingerprint']=fingerprint(assignment)
        with self.assertRaises(ValueError):freeze_selection(s,sid,'SPY',v)
        review=describe(s,sid,'SPY',v)
        self.assertTrue(review['policy_warning']);self.assertEqual(12,review['exit_policy']['gain_pct'])
        s.update(save(s,sid,'SPY',v,review['revision'],{},'test'))
        self.assertEqual(12,freeze_selection(s,sid,'SPY',v)['premium_exit_policy']['gain_pct'])
    def test_configured_supertrend_sma_atr_restores_actual_history(self):
        from dataclasses import replace
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from research.engine.strategies.supertrend_reversal import SuperTrendReversal
        from strategy_health.supertrend_exit import entry_state,restored
        engine=SuperTrendReversal();engine=SuperTrendReversal(replace(engine.config,use_rma_atr=False,atr_period=3))
        engine._configuration_revision='explicit-save';engine._last_timestamp=datetime(2026,11,13,10,tzinfo=ZoneInfo('America/New_York'))
        engine._atr_value=2;engine._last_close=100;engine._up=98;engine._down=102;engine._trend=1;engine._tr_values=[1,2,3]
        seed=entry_state(engine);result=restored(seed,(engine._last_timestamp+timedelta(minutes=5)).replace(tzinfo=None),'bullish')
        self.assertIsNotNone(result);self.assertEqual([1,2,3],result._tr_values)
        self.assertIsNot(result._tr_values,engine._tr_values)
