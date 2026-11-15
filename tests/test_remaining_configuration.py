"""Saved values drive real entry/exit calculations; never uses a broker."""
import json
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch,MagicMock
import pandas as pd
from config import engine_parameters as ep, execution_parameters as xp
from config.strategy_catalog import REVIEWED_STRATEGIES

class RemainingConfigurationTests(unittest.TestCase):
    def settings(self,sid,ticker,entry=None,execution=None):
        s={'paper_trading':True,'active_broker_account_id':'isolated'}
        version=REVIEWED_STRATEGIES[sid].version
        view=ep.describe(s,sid,ticker,version)
        return {**s,**ep.save(s,sid,ticker,version,view['revision'],entry or {},'test',execution=execution or {})}
    def test_orb_range_direction_target_and_stop_use_saved_values(self):
        from tests.test_orb_retouch_execution import frame
        from trading.orb_retouch_execution import update_one_minute_orb_retouch as update
        prices=frame([100.]*5+[99.],[100.5]*5+[99.2],[99.5]*5+[98.8])
        kwargs=dict(ticker='TSLA',quote_price=99.5,now=datetime(2026,1,2,9,36))
        self.assertIsNone(update({},prices,**kwargs)[0])
        s=self.settings('V2_ORB_PULLBACK','TSLA',{'opening_range_minutes':5,'allow_short':True,'stop_range_fraction':.5,'reward_risk':3.})
        with ep.for_pair(json.loads(json.dumps(s)),'V2_ORB_PULLBACK','TSLA'):
            signal,status=update({},prices,**kwargs)
            self.assertEqual('bearish',signal.direction)
            self.assertEqual(100.,signal.meta['v2_stop'])
            self.assertEqual(98.,signal.meta['v2_target'])
            self.assertEqual('first_retouch_quote',status)
        self.assertIsNone(update({},prices,**kwargs)[0])
    def test_saved_fvg_stop_and_reward_change_actual_levels(self):
        from tests.test_spy_afternoon_fvg_v2 import _valid_bars
        from strategies.spy_afternoon_fvg_v2 import _signal_from_completed_bars as _latest_candidate
        bars=_valid_bars();baseline=_latest_candidate(bars)
        s=self.settings('V2_SPY_AFTERNOON_FVG','SPY',{'stop_atr_multiple':3.,'reward_risk':4.})
        with ep.for_pair(s,'V2_SPY_AFTERNOON_FVG','SPY'):changed=_latest_candidate(bars)
        self.assertLess(changed.meta['v2_stop'],baseline.meta['v2_stop'])
        self.assertAlmostEqual((changed.meta['v2_target']-changed.meta['v2_entry_reference'])/(changed.meta['v2_entry_reference']-changed.meta['v2_stop']),4.)
    def test_custom_entry_bars_are_complete_and_gap_free(self):
        from config.strategy_inputs import INTERVALS
        from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars
        start=pd.Timestamp('2026-11-13 09:30')
        for interval in INTERVALS:
            s=self.settings('V2_SPY_TREND_CONT','SPY',{'entry_timeframe_minutes':interval})
            frame=pd.DataFrame([dict(time=start+timedelta(minutes=i),open=100,high=101,low=99,close=100,volume=10) for i in range(interval)])
            with ep.for_pair(s,'V2_SPY_TREND_CONT','SPY'):
                self.assertEqual(0,len(_complete_five_minute_bars(frame,now=start+timedelta(minutes=interval,seconds=-1))))
                self.assertEqual(1,len(_complete_five_minute_bars(frame,now=start+timedelta(minutes=interval))))
                if interval>1:self.assertEqual(0,len(_complete_five_minute_bars(frame.drop(index=0),now=start+timedelta(minutes=interval))))
    def test_context_volume_window_midpoint_and_time_gate(self):
        from tests.test_context_strategy_observers import _nr7_frame
        from strategies import context_strategy_observers as module
        sid=module.ORB_NR7_INSIDE;prices,now=_nr7_frame();now=prices.iloc[-1].time+timedelta(minutes=1)
        module._emitted.clear();baseline=module.evaluate_orb_nr7_inside(prices,ticker='SPY',now=now)
        self.assertIsNotNone(baseline)
        s=self.settings(sid,'SPY',{'volume_ratio_minimum':5.,'volume_lookback_bars':10})
        with ep.for_pair(s,sid,'SPY'):self.assertIsNone(module.evaluate_orb_nr7_inside(prices,ticker='SPY',now=now))
        s=self.settings(sid,'SPY',{'midpoint_fraction':.25,'entry_end':'10:30'})
        module._emitted.clear()
        with ep.for_pair(s,sid,'SPY'):signal=module.evaluate_orb_nr7_inside(prices,ticker='SPY',now=now)
        self.assertAlmostEqual(signal.meta['or_midpoint'],signal.meta['or_low']+.25*(signal.meta['or_high']-signal.meta['or_low']))
        s=self.settings(sid,'SPY',{'entry_start':'10:00'})
        module._emitted.clear()
        with ep.for_pair(s,sid,'SPY'):self.assertIsNone(module.evaluate_orb_nr7_inside(prices,ticker='SPY',now=now))
    def test_custom_target_ranking_changes_selected_contract(self):
        from trading.research_contract_selection import _leaderboard,ResearchContractProfile
        candidates=[(2,1.,.01,'a',{'ask':2.}), (2,2.,.01,'b',{'ask':3.})]
        p=ResearchContractProfile('test',0,7,1,10,.08,'target_150_250','test',2.8,3.2,3.)
        result,policy=_leaderboard(candidates,p)
        self.assertEqual('target_150_250',policy)
        # target ranking is attached only to B, even though A is nearer OTM.
        self.assertIn('b',str(result))
        from dataclasses import replace
        self.assertNotEqual(_leaderboard(candidates,replace(p,target_minimum_premium=1.5,target_maximum_premium=2.5,target_premium=2.))[0],result)
    def test_native_partial_quantity_uses_frozen_percent_after_restart(self):
        from trading.research_order_exit import partial_remaining
        sid='RESEARCH_CTX_ORB_ATR10_V2';s=self.settings(sid,'SPY',execution={'native_exit':{'partial_sell_pct':25.}})
        trade=dict(id=1,strategy_id=sid,ticker='SPY',contracts=8,broker_account_id='test',strategy_context_json=xp.freeze(s,sid,'SPY'))
        trade=json.loads(json.dumps(trade));conn=MagicMock();conn.__enter__.return_value=conn
        with patch('database.get_conn',return_value=conn):
            conn.execute.return_value.fetchone.return_value=(0,)
            self.assertEqual(2,partial_remaining(trade))
            conn.execute.return_value.fetchone.return_value=(1,);trade['contracts']=7
            self.assertEqual(1,partial_remaining(trade))
            conn.execute.return_value.fetchone.return_value=(2,);trade['contracts']=6
            self.assertEqual(0,partial_remaining(trade))
    def test_frozen_structural_interval_decides_only_at_its_close(self):
        from strategy_health.impulse_exit import first_exit
        from strategies.base import Signal
        sid='V2_IMPULSE_ANCHORED_VWAP_PULLBACK';s=self.settings(sid,'NVDA',{'entry_timeframe_minutes':4}, {'native_exit':{'structural_timeframe_minutes':4}})
        signal=Signal(strategy_id=sid,direction='bullish',confidence=.8,rvol=0,trigger_bar=pd.Timestamp('2026-11-13 10:02'),meta={})
        with ep.for_pair(s,sid,'NVDA'):ep.attach(signal)
        trade=dict(strategy_id=sid,ticker='NVDA',strategy_context_json=json.dumps({**signal.meta,**xp.freeze(s,sid,'NVDA')}))
        at=pd.Timestamp('2026-11-13 10:02:00-05:00');frame=pd.DataFrame([dict(time=at+timedelta(minutes=i),open=100,high=101,low=98,close=100) for i in range(8)])
        args=dict(entry_at=at,entry_quote_at=at,stop=99,target=110,direction='bullish')
        with xp.from_trade(trade):
            self.assertIsNone(first_exit(frame,**args,now=at+timedelta(minutes=7)))
            self.assertEqual(((at+timedelta(minutes=8)).tz_localize(None),'underlying_stop'),first_exit(frame,**args,now=at+timedelta(minutes=8)))
        self.assertEqual('invalid_entry',first_exit(frame,**args,now=at+timedelta(minutes=8))[1])
    def test_nullable_date_and_impossible_time_alignment(self):
        sid='V2_SPY_ORB_RSI_MACD_SHORT'
        s=self.settings(sid,'SPY',{'active_date':None})
        with ep.for_pair(s,sid,'SPY'):self.assertIsNone(ep.parameter('active_date','bad'))
        with self.assertRaises(ValueError):self.settings('V2_TSLA_TWO_LEG_TREND_PULLBACK','TSLA',{'entry_timeframe_minutes':4})
        self.settings('V2_TSLA_TWO_LEG_TREND_PULLBACK','TSLA',{'entry_timeframe_minutes':4,'reference_time':'09:46'})
    def test_two_leg_stop_multiple_reaches_entry_calculation(self):
        from tests.test_two_leg_execution import _bars,ET
        from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback as update
        now=ET.localize(datetime(2026,8,12,10,3))
        baseline,_=update({},_bars(),ticker='TSLA',now=now)
        s=self.settings('V2_TSLA_TWO_LEG_TREND_PULLBACK','TSLA',{'stop_atr_multiple':3.})
        with ep.for_pair(s,'V2_TSLA_TWO_LEG_TREND_PULLBACK','TSLA'):
            changed,_=update({},_bars(),ticker='TSLA',now=now)
        self.assertLess(changed.meta['v2_stop'],baseline.meta['v2_stop'])
    def test_custom_supertrend_interval_keeps_session_close(self):
        from tests.test_supertrend_exit_measurement import seed
        from strategy_health.supertrend_exit import first_exit
        sid='APPROVED_TV_SUPERTREND_REVERSAL_V4'
        s=self.settings(sid,'SPY',execution={'native_exit':{'structural_timeframe_minutes':60}})
        trade=dict(strategy_id=sid,ticker='SPY',strategy_context_json=xp.freeze(s,sid,'SPY'))
        start=datetime(2026,9,10,15,50)
        frame=pd.DataFrame([dict(time=start+timedelta(minutes=i),open=100,high=101,low=99,close=100,volume=10) for i in range(10)])
        with xp.from_trade(trade):
            result=first_exit(frame,entry_at=start,entry_quote_at=start,direction='bullish',seed=seed(bar_time='2026-09-10T15:45'),now=datetime(2026,9,10,16))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),result)
    def test_custom_vwap_interval_waits_for_complete_observations(self):
        from trading.vwap_displacement_exit import evaluate_vwap_displacement_exit as evaluate
        sid='CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'
        s=self.settings(sid,'AMZN',execution={'native_exit':{'structural_timeframe_minutes':4}})
        trade=dict(strategy_id=sid,ticker='AMZN',strategy_context_json=xp.freeze(s,sid,'AMZN'))
        start=datetime(2026,11,13,9,30)
        frame=pd.DataFrame([dict(time=start+timedelta(minutes=i),open=100,high=102,low=98,close=99,volume=10) for i in range(8)])
        args=dict(entry_time=start+timedelta(minutes=4),one_minute_bars=frame,five_minute_bars=None,strategy_context={})
        with xp.from_trade(trade):
            self.assertEqual((False,'hold'),evaluate(now=start+timedelta(minutes=7),**args))
            self.assertEqual((True,'vwap_displacement_4m_close_below_vwap'),evaluate(now=start+timedelta(minutes=8),**args))
            args['one_minute_bars']=frame.drop(index=6)
            self.assertEqual((False,'hold'),evaluate(now=start+timedelta(minutes=8),**args))
