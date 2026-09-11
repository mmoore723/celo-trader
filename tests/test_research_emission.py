from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from research.engine.models import Bar, Side, Signal
from trading.research_emission import DAILY_LATCHES, EXPANDED_IDS, prepare_bar
from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES, _latest_candidate


class DailyRule:
    def __init__(self):
        self._emitted_day = None
        self._long_armed = False
        self.seen = 0

    def evaluate(self, bars):
        self.seen += 1
        bar = bars[-1]
        if self._emitted_day == bar.timestamp.date():
            return None
        self._emitted_day = bar.timestamp.date()
        return Signal('V2_ORB_CONFIRMED_BREAKOUT', Side.LONG, bar.timestamp, bar.close, bar.low, bar.high, {})


class ResearchEmissionTests(unittest.TestCase):
    def test_every_registered_latch_exists_and_only_expected_field_changes(self):
        for sid, (field, blank) in DAILY_LATCHES.items():
            with self.subTest(sid=sid):
                strategy = TESTED_RESEARCH_STRATEGIES[sid].factory()
                self.assertTrue(hasattr(strategy, field))
                setattr(strategy, field, True)
                before = strategy.__dict__.copy()
                prepare_bar(sid, strategy)
                self.assertEqual({**before, field: blank}, strategy.__dict__)

    def test_research_sees_later_bar_native_source_keeps_daily_limit(self):
        first = datetime(2026,9,11,10)
        bars = tuple(Bar(first+timedelta(minutes=i),100,102,99,101,1000) for i in range(3))
        native = DailyRule()
        self.assertIsNone(_latest_candidate(native, bars))
        research = DailyRule()
        result = _latest_candidate(research, bars, research_strategy_id='V2_ORB_CONFIRMED_BREAKOUT')
        self.assertEqual(bars[-1].timestamp,result.timestamp)
        self.assertFalse(research._long_armed)  # Structural rearm is not cleared.
        self.assertEqual(3,research.seen)

    def test_unknown_latch_change_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'latch changed'):
            prepare_bar('V2_ORB_CONFIRMED_BREAKOUT', SimpleNamespace())

    def test_seven_expanded_versions_do_not_inherit_capped_evidence(self):
        self.assertEqual(7,len(EXPANDED_IDS))
        for sid in EXPANDED_IDS:
            self.assertEqual('research.2',TESTED_RESEARCH_STRATEGIES[sid].version)
        self.assertEqual('research.1',TESTED_RESEARCH_STRATEGIES['V2_OPENING_MOMENTUM_RTH_EXPLORATORY'].version)
        self.assertEqual('research.3',TESTED_RESEARCH_STRATEGIES['V2_EMA_PULLBACK_RTH'].version)
