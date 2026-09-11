from datetime import timedelta
import json
import unittest
import pandas as pd

from trading import failed_range_research as research
from strategies import spy_failed_range_recovery_v2 as source
from tests.test_spy_failed_range_recovery_v2 import _frame

OPENING = [(100,101,99,100)]*15
BREAK = (101,101.4,100.9,101.2)
FAIL = (101.3,101.3,100.8,100.9)


class FailedRangeResearchTests(unittest.TestCase):
    def setUp(self):
        research._last_trigger.clear()
        source._emitted_trigger_by_session.clear()

    def run_entry(self, rows, *, now=None, ticker='META', scope='research_worker:a'):
        frame = _frame(rows)
        return research.evaluate(frame,ticker=ticker,scope=scope,
            now=now or frame.iloc[-1]['time']+timedelta(minutes=1))

    def test_first_levels_equal_reviewed_and_later_episode_is_not_blocked(self):
        rows = OPENING+[BREAK,FAIL]
        first = self.run_entry(rows)
        native = source.evaluate(_frame(rows),ticker='SPY',now=pd.Timestamp('2026-08-10 09:47'))
        self.assertIsNotNone(first)
        for key,value in native.meta.items():
            if key != 'reviewed_paid_quote_rule':
                self.assertEqual(value,first.meta[key])
        self.assertEqual(native.trigger_bar,first.trigger_bar)
        self.assertIsNone(self.run_entry(rows))
        # New outside close, then its own failure: no wait for another play's exit.
        later = rows+[BREAK,FAIL]
        second = self.run_entry(later)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.meta['research_episode_anchor'],second.meta['research_episode_anchor'])
        self.assertIsNone(source.evaluate(_frame(later),ticker='SPY',now=pd.Timestamp('2026-08-10 09:49')))

    def test_inside_candles_do_not_repeat_consumed_episode(self):
        self.assertIsNone(self.run_entry(OPENING+[BREAK,FAIL,FAIL,FAIL]))

    def test_failed_room_check_does_not_block_next_break(self):
        no_room = (100.1,100.2,99.9,100)
        self.assertIsNone(self.run_entry(OPENING+[BREAK,no_room]))
        self.assertIsNotNone(self.run_entry(OPENING+[BREAK,no_room,BREAK,FAIL]))

    def test_short_break_mirrors_long_and_rearms(self):
        mirror = lambda row: (200-row[0],200-row[2],200-row[1],200-row[3])
        candidate = self.run_entry([mirror(r) for r in OPENING+[BREAK,FAIL,BREAK,FAIL]])
        self.assertEqual('bullish',candidate.direction)
        self.assertLess(candidate.meta['v2_stop'],candidate.meta['v2_entry_reference'])
        self.assertGreater(candidate.meta['v2_target'],candidate.meta['v2_entry_reference'])

    def test_stale_forming_prior_day_and_late_breakout_rejected(self):
        rows = OPENING+[BREAK,FAIL]
        for now in ('2026-08-10 09:46:59','2026-08-10 09:48','2026-08-11 09:47'):
            self.assertIsNone(self.run_entry(rows,now=pd.Timestamp(now)))
        self.assertIsNone(self.run_entry(OPENING+[(100,101,99,100)]*77+[BREAK,FAIL]))

    def test_account_ticker_timezone_and_bad_data(self):
        rows = OPENING+[BREAK,FAIL]
        for scope,ticker in [('research_worker:a','META'),('research_worker:b','META'),('research_worker:a','NVS')]:
            self.assertIsNotNone(self.run_entry(rows,scope=scope,ticker=ticker))
        frame = _frame(rows)
        frame['time'] = frame['time'].dt.tz_localize('America/New_York').dt.tz_convert('UTC')
        self.assertIsNotNone(research.evaluate(frame,ticker='SPY',scope='research_worker:a',now='2026-08-10T13:47:00Z'))
        self.assertIsNone(self.run_entry(OPENING+[BREAK,(101.3,101.3,100.8,float('nan'))]))

    def test_order_scope_rejected_and_native_integrity_preserved(self):
        with self.assertRaises(ValueError):
            self.run_entry(OPENING+[BREAK,FAIL],scope='live')
        from config.strategy_catalog import reviewed_strategy_integrity_errors
        self.assertEqual({},reviewed_strategy_integrity_errors())
        self.assertIsNone(source.evaluate(_frame(OPENING+[BREAK,FAIL]),ticker='META',now='2026-08-10 09:47'))

    def test_expanded_results_do_not_inherit_first_only_proof(self):
        from strategy_health.research_matrix import _current_rule_samples
        rows = [{'direction':'bearish','metadata_json':json.dumps({'strategy_version':v})}
                for v in ('2.1.0','2.1.0.research.2')]
        current,rejected,unscored,previous = _current_rule_samples(rows,source.STRATEGY_ID,'META')
        self.assertEqual([rows[1]],current)
        self.assertEqual((0,0,1),(rejected,unscored,previous))
