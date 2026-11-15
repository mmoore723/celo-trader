"""Cross-registry save/read/execution audit. All settings are isolated dictionaries."""
import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from config import engine_parameters as ep, execution_parameters as xp
from config.strategy_catalog import REVIEWED_STRATEGIES
from config.research_order_specs import SPECS
from config.research_pair_policy import selected

class ConfigurationAuditTests(unittest.TestCase):
    def base(self):return {'paper_trading':True,'active_broker_account_id':'audit','risk_per_trade':.01,'max_position_dollars_pct':10}
    def ticker(self,sid):
        rule=REVIEWED_STRATEGIES[sid];allowed=SPECS[sid].allowed_tickers if sid in SPECS else rule.tickers
        return next(iter(allowed or rule.tickers),'SPY')
    def save(self,s,sid,ticker,**kwargs):
        v=REVIEWED_STRATEGIES[sid].version;d=ep.describe(s,sid,ticker,v)
        entry={f['key']:f['value'] for f in d['entry']}
        return {**s,**ep.save(s,sid,ticker,v,d['revision'],entry,'audit',**kwargs)}
    def test_every_route_can_save_displayed_values_and_roundtrip(self):
        for sid,r in REVIEWED_STRATEGIES.items():
            with self.subTest(strategy=sid):
                s=self.base();before=deepcopy(s);t=self.ticker(sid)
                view=ep.describe(s,sid,t,r.version)
                saved=json.loads(json.dumps(self.save(s,sid,t)))
                after=ep.describe(saved,sid,t,r.version)
                self.assertEqual(view['entry'],after['entry'])
                self.assertEqual(view['execution'],after['execution'])
                self.assertEqual(before,s)
                self.assertEqual(before,{k:v for k,v in saved.items() if k!=ep.KEY})
                with ep.for_pair(saved,sid,t):
                    for f in view['entry']:self.assertEqual(f['value'],ep.encode(ep.parameter(f['key'],None)))
    def test_qqq_alias_uses_saved_ema_and_failed_range_alias_saves(self):
        from strategies.market_structure import TrendContinuationConfig
        sid='RESEARCH_QQQ_TREND_V2';s=self.base();v=REVIEWED_STRATEGIES[sid].version
        d=ep.describe(s,sid,'QQQ',v)
        s.update(ep.save(s,sid,'QQQ',v,d['revision'],{'fast_ema':7},'audit'))
        with ep.for_pair(s,sid,'QQQ'):self.assertEqual(7,ep.configured(TrendContinuationConfig()).fast_ema)
        self.save(self.base(),'RESEARCH_FAILED_RANGE_V2',self.ticker('RESEARCH_FAILED_RANGE_V2'))
    def test_selected_timer_stays_visible_with_unrelated_native_override(self):
        sid='V2_VWAP_PULLBACK';s=self.save(self.base(),sid,'AMZN',contract_timer={'exit_minutes':60,'contract_policy':'highest_volume_150_1000'},execution={'native_exit':{'max_hold_bars':20}})
        view=ep.describe(s,sid,'AMZN',REVIEWED_STRATEGIES[sid].version)
        self.assertEqual(60,view['execution']['native_exit']['hold_minutes'])
        self.assertEqual('highest_volume_150_1000',view['execution']['contract']['primary_policy'])
        from trading.research_order_exit import evaluate_exit
        at=datetime.fromisoformat('2026-11-13T10:00:00-05:00')
        meta={**xp.freeze(s,sid,'AMZN'),'strategy_version':SPECS[sid].version,'research_order_route':'exact_research_v1','selected_test_policy':selected(s,sid,'AMZN',SPECS[sid].version)}
        trade=dict(strategy_id=sid,ticker='AMZN',strategy_context_json=json.dumps(meta))
        self.assertEqual((False,'hold'),evaluate_exit(trade,at,at+timedelta(minutes=59),None))
        self.assertEqual((True,'selected_test_60m'),evaluate_exit(trade,at,at+timedelta(minutes=60),None))
        s=self.save(s,sid,'AMZN',contract_timer={'exit_minutes':60,'contract_policy':None},execution={'native_exit':{'hold_minutes':45}})
        self.assertEqual(45,ep.describe(s,sid,'AMZN',SPECS[sid].version)['execution']['native_exit']['hold_minutes'])
        # Already-open position retains the old 60-minute setting.
        self.assertEqual((False,'hold'),evaluate_exit(trade,at,at+timedelta(minutes=45),None))
    def test_timer_can_be_removed_without_losing_other_controls(self):
        sid='V2_VWAP_PULLBACK';s=self.save(self.base(),sid,'AMZN',contract_timer={'exit_minutes':60,'contract_policy':None},execution={'native_exit':{'max_hold_bars':20}})
        s=self.save(s,sid,'AMZN',contract_timer={'exit_minutes':None,'contract_policy':None},execution={'native_exit':{'max_hold_bars':20}})
        view=ep.describe(s,sid,'AMZN',SPECS[sid].version)
        self.assertNotIn('hold_minutes',view['execution']['native_exit'])
        self.assertEqual(20,view['execution']['native_exit']['max_hold_bars'])

    def test_retouch_rejects_values_the_engine_cannot_execute(self):
        sid='V2_ORB_PULLBACK';s=self.base();v=REVIEWED_STRATEGIES[sid].version
        view=ep.describe(s,sid,'TSLA',v)
        for value in (.01,.1,1):
            with self.assertRaises(ValueError):ep.save(s,sid,'TSLA',v,view['revision'],{'retouch_tolerance_pct':value},'audit')
