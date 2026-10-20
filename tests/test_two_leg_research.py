import json
import unittest
from unittest.mock import Mock, patch
import pandas as pd
from trading import two_leg_research as research
from trading import two_leg_trend_pullback_execution as source
from trading.entry.injected_setups import evaluate_injected_setups, TWO_LEG
from tests.test_two_leg_execution import _bars, _bearish_bars


def twice(frame):
    rows = frame.to_dict('records')
    flat = dict(rows[0])
    extra = [flat.copy() for _ in range(20)]+[dict(r) for r in rows[-3:]]
    for i,row in enumerate(extra):
        row['time'] = rows[-1]['time']+pd.Timedelta(minutes=i+1)
    return pd.DataFrame(rows+extra)


class TwoLegResearchTests(unittest.TestCase):
    def run_entry(self,frame,state=None,**kwargs):
        return research.update(state if state is not None else {},frame,ticker='META',
            scope='research_worker:a',now=frame.iloc[-1]['time']+pd.Timedelta(minutes=1),**kwargs)[0]

    def test_both_directions_preserve_every_first_signal_field(self):
        for frame in (_bars(),_bearish_bars()):
            native,_ = source.update_two_leg_trend_pullback({},frame,ticker='TSLA',now=frame.iloc[-1]['time']+pd.Timedelta(minutes=1))
            expanded = self.run_entry(frame)
            self.assertIsNotNone(expanded)
            self.assertEqual(native.direction,expanded.direction)
            self.assertEqual(native.trigger_bar,expanded.trigger_bar)
            for key,value in native.meta.items():
                self.assertEqual(value,expanded.meta[key],key)

    def test_fresh_impulse_after_emission_is_allowed_without_waiting_for_exit(self):
        for frame in (_bars(),_bearish_bars()):
            state={}
            first=self.run_entry(frame,state)
            self.assertIsNone(self.run_entry(frame,state))
            later=twice(frame)
            second=self.run_entry(later,state)
            self.assertIsNotNone(second)
            self.assertNotEqual(first.meta['research_episode_anchor'],second.meta['research_episode_anchor'])
            self.assertLess((second.trigger_bar-first.trigger_bar).total_seconds(),90*60)
            native,_=source.update_two_leg_trend_pullback({},later,ticker='TSLA',now=later.iloc[-1]['time']+pd.Timedelta(minutes=1))
            self.assertIsNotNone(native)
            self.assertEqual(second.trigger_bar, native.trigger_bar)

    def test_rejected_reclaim_cannot_be_rescued_but_new_episode_can_pass(self):
        frame=_bars();frame.loc[frame.index[-1],['open','high','low','close']]=[100.85,101.1,100.6,100.9]
        self.assertIsNone(self.run_entry(frame))
        later=twice(frame)
        later.loc[later.index[-1],['open','high','low','close']]=[100.7,101.2,100.6,101.1]
        self.assertIsNotNone(self.run_entry(later))

    def test_forming_stale_previous_day_invalid_and_late_frames(self):
        frame=_bars()
        for now in (frame.iloc[-1]['time'],frame.iloc[-1]['time']+pd.Timedelta(minutes=2),frame.iloc[-1]['time']+pd.Timedelta(days=1,minutes=1)):
            self.assertIsNone(research.update({},frame,ticker='META',scope='research_worker:a',now=now)[0])
        frame.loc[frame.index[-1],'close']=float('nan')
        self.assertIsNone(self.run_entry(frame))
        frame=_bars();frame.loc[frame.index[-3:],'time']+=pd.Timedelta(hours=2)
        self.assertIsNone(self.run_entry(frame))

    def test_scope_ticker_and_session_isolation(self):
        state={};frame=_bars();now=frame.iloc[-1]['time']+pd.Timedelta(minutes=1)
        for scope,ticker in [('research_worker:a','META'),('research_worker:b','META'),('research_worker:a','NVS')]:
            self.assertIsNotNone(research.update(state,frame,ticker=ticker,scope=scope,now=now)[0])
        with self.assertRaises(ValueError):
            research.update(state,frame,ticker='TSLA',scope='live',now=now)
        from config.strategy_catalog import reviewed_strategy_integrity_errors
        self.assertEqual({},reviewed_strategy_integrity_errors())

    def test_worker_injection_only_and_native_daily_state_unchanged(self):
        state={};frame=twice(_bars());now=frame.iloc[-1]['time']+pd.Timedelta(minutes=1)
        with patch('trading.entry.injected_setups._now_et',return_value=now):
            found,_,_=evaluate_injected_setups(state,frame,'TSLA',set(),{TWO_LEG},Mock(),{},research_scope='research_worker:a')
            self.assertEqual(1,len(found));self.assertTrue(found[0].meta['observation_only'])
            self.assertFalse(state['v2_tsla_two_leg_trend_pullback']['TSLA'].get('emitted'))
            with self.assertRaises(ValueError):
                evaluate_injected_setups(state,frame,'TSLA',{TWO_LEG},set(),Mock(),{},research_scope='research_worker:a')
            native,_,_=evaluate_injected_setups({},frame,'TSLA',{TWO_LEG},set(),Mock(),{})
            self.assertEqual(1,len(native))
            self.assertFalse(native[0].meta.get('observation_only'))

    def test_current_proof_is_only_expanded_version(self):
        from strategy_health.research_matrix import _current_rule_samples
        rows=[{'direction':'bullish','metadata_json':json.dumps({'strategy_version':v})} for v in ('2.1.0','2.1.0.research.2')]
        selected,rejected,unscored,previous=_current_rule_samples(rows,TWO_LEG,'META')
        self.assertEqual([rows[1]],selected);self.assertEqual((0,0,1),(rejected,unscored,previous))
