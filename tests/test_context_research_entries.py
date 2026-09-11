from datetime import timedelta
import json
import unittest
from unittest.mock import patch
import pandas as pd

from strategies import context_strategy_observers as source
from trading import context_research_entries as research
from tests.test_context_strategy_observers import _nr7_frame, _row, _vwap_displacement_frame


class ContextResearchEntriesTests(unittest.TestCase):
    def setUp(self):
        source._emitted.clear()
        research._last_trigger.clear()

    def run_entry(self, frame, sid, now, **kwargs):
        return research.evaluate(frame,strategy_id=sid,ticker='META',scope='research_worker:test',now=now,**kwargs)

    def test_nr7_first_levels_match_and_later_bar_is_not_blocked(self):
        frame, _ = _nr7_frame()
        now = frame.iloc[-1]['time']+timedelta(minutes=1)
        original = source.evaluate_orb_nr7_inside(frame,ticker='SPY',now=now)
        candidate = self.run_entry(frame,source.ORB_NR7_INSIDE,now)
        self.assertIsNotNone(candidate)
        for key,value in original.meta.items():
            self.assertEqual(value,candidate.meta[key])
        self.assertEqual(original.trigger_bar,candidate.trigger_bar)
        self.assertIsNone(self.run_entry(frame,source.ORB_NR7_INSIDE,now))
        attrs = frame.attrs.copy()
        later = pd.concat([frame,pd.DataFrame([_row(now,close=101.1,high=101.3,volume=250)])],ignore_index=True)
        later.attrs = attrs
        # Existing reviewed path stops on its already-recorded first bar.
        self.assertIsNone(source.evaluate_orb_nr7_inside(later,ticker='SPY',now=now+timedelta(minutes=1)))
        self.assertEqual(now+timedelta(minutes=1),self.run_entry(later,source.ORB_NR7_INSIDE,now+timedelta(minutes=1)).trigger_bar)

    def test_stale_and_forming_entries_are_not_repriced(self):
        frame,_ = _nr7_frame()
        trigger = frame.iloc[-1]['time']+timedelta(minutes=1)
        self.assertIsNone(self.run_entry(frame,source.ORB_NR7_INSIDE,trigger+timedelta(minutes=1)))
        self.assertIsNone(self.run_entry(frame,source.ORB_NR7_INSIDE,trigger-timedelta(seconds=1)))
        self.assertIsNotNone(self.run_entry(frame,source.ORB_NR7_INSIDE,trigger+timedelta(seconds=20)))

    def test_vwap_retains_first_levels_and_allows_later_completed_reclaim(self):
        frame,now = _vwap_displacement_frame()
        original = source.evaluate_vwap_displacement(frame,ticker='TSLA',now=now)
        candidate = self.run_entry(frame,source.VWAP_DISPLACEMENT_LONG,now)
        self.assertIsNotNone(candidate)
        for key,value in original.meta.items():
            if key != 'observation_only':
                self.assertEqual(value,candidate.meta[key])
        attrs = frame.attrs.copy()
        extra = [_row(now+timedelta(minutes=i),close=102.3,high=102.6,low=100) for i in range(5)]
        later = pd.concat([frame,pd.DataFrame(extra)],ignore_index=True)
        later.attrs = attrs
        self.assertIsNone(source.evaluate_vwap_displacement(later,ticker='TSLA',now=now+timedelta(minutes=5)))
        second = self.run_entry(later,source.VWAP_DISPLACEMENT_LONG,now+timedelta(minutes=5))
        self.assertIsNotNone(second)
        self.assertEqual(now+timedelta(minutes=5),second.trigger_bar)
        self.assertTrue(second.meta['observation_only'])

    def test_gates_are_not_weakened(self):
        frame,_ = _nr7_frame()
        now = frame.iloc[-1]['time']+timedelta(minutes=1)
        weak = frame.copy(); weak.loc[weak.index[-1],'volume'] = 140
        self.assertIsNone(self.run_entry(weak,source.ORB_NR7_INSIDE,now))
        invalid = frame.copy(); invalid.loc[invalid.index[-1],'volume'] = float('nan')
        self.assertIsNone(self.run_entry(invalid,source.ORB_NR7_INSIDE,now))
        frame.attrs.clear()
        self.assertIsNone(self.run_entry(frame,source.ORB_NR7_INSIDE,now))

    def test_scope_and_ticker_do_not_share_deduplication(self):
        frame,_ = _nr7_frame(); now=frame.iloc[-1]['time']+timedelta(minutes=1)
        for scope,ticker in [('research_worker:a','META'),('research_worker:b','META'),('research_worker:a','NVS')]:
            self.assertIsNotNone(research.evaluate(frame,strategy_id=source.ORB_NR7_INSIDE,
                ticker=ticker,scope=scope,now=now))

    def test_price_operations_do_not_deepcopy_or_remove_context_attrs(self):
        class NoDeepCopy:
            def __deepcopy__(self, memo):
                raise AssertionError('History metadata must not be deep-copied')
        frame,_ = _nr7_frame()
        now = frame.iloc[-1]['time']+timedelta(minutes=1)
        tape = frame.attrs['multi_session_bars']
        frame.attrs['copy_detector'] = NoDeepCopy()
        self.assertIsNotNone(self.run_entry(frame,source.ORB_NR7_INSIDE,now))
        self.assertIs(tape,frame.attrs['multi_session_bars'])
        self.assertIn('copy_detector',frame.attrs)

    def test_atr10_and_ker_use_their_own_context_gates(self):
        frame,_ = _nr7_frame(); now=frame.iloc[-1]['time']+timedelta(minutes=1)
        with patch.object(source,'_atr10_gate',return_value=(False,{})):
            self.assertIsNone(self.run_entry(frame,source.ORB_ATR10_LONG,now))
        with patch.object(source,'_atr10_gate',return_value=(True,{'atr10':2})):
            self.assertIsNotNone(self.run_entry(frame,source.ORB_ATR10_LONG,now))
        frame,now = _vwap_displacement_frame()
        with patch.object(source,'_kaufman',return_value=.6):
            self.assertIsNone(self.run_entry(frame,source.VWAP_KER10_LONG,now))
        with patch.object(source,'_kaufman',return_value=.61):
            self.assertIsNotNone(self.run_entry(frame,source.VWAP_KER10_LONG,now))

    def test_execution_scope_rejected_and_reviewed_integrity_unchanged(self):
        with self.assertRaises(ValueError):
            research.evaluate(pd.DataFrame(),strategy_id=source.ORB_NR7_INSIDE,ticker='SPY',scope='live')
        from config.strategy_catalog import reviewed_strategy_integrity_errors
        self.assertEqual({},reviewed_strategy_integrity_errors())

    def test_old_first_only_evidence_remains_separate(self):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        from strategy_health.research_matrix import _current_rule_samples
        for sid in research.STRATEGY_IDS:
            old=REVIEWED_STRATEGIES[sid].version
            rows=[{'direction':'bullish','metadata_json':json.dumps({'strategy_version':version})}
                  for version in (old,research.evidence_version(sid,old))]
            selected,rejected,unscored,previous=_current_rule_samples(rows,sid,'META')
            self.assertEqual([rows[1]],selected)
            self.assertEqual((0,0,1),(rejected,unscored,previous))
