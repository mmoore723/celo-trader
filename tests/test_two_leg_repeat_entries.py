import unittest
import pandas as pd
from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback
from trading.research_versions import capture_versions, evidence_version
from tests.test_two_leg_execution import _bars, _bearish_bars
from tests.test_two_leg_research import twice


class RepeatEntryTests(unittest.TestCase):
    def signal(self, frame, state, now=None):
        return update_two_leg_trend_pullback(
            state, frame, ticker="TSLA",
            now=now if now is not None else frame.iloc[-1]["time"] + pd.Timedelta(minutes=1),
        )

    def test_two_distinct_setups_both_directions_and_duplicate_protection(self):
        for frame in (_bars(), _bearish_bars()):
            state = {}
            first, _ = self.signal(frame, state)
            self.assertIsNotNone(first)
            self.assertIsNone(self.signal(frame, state)[0])
            later = twice(frame)
            second, _ = self.signal(later, state)
            self.assertIsNotNone(second)
            self.assertGreater(second.trigger_bar, first.trigger_bar)
            self.assertEqual(first.direction, second.direction)
            self.assertIsNone(self.signal(later, state)[0])

    def test_restart_does_not_reemit_stale_reclaim(self):
        frame = _bars()
        signal, status = self.signal(frame, {}, frame.iloc[-1]["time"] + pd.Timedelta(minutes=2))
        self.assertIsNone(signal)
        self.assertEqual("stale_reclaim", status)

    def test_rejected_episode_does_not_block_new_episode(self):
        frame = _bars()
        frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [100.85, 101.1, 100.6, 100.9]
        self.assertIsNone(self.signal(frame, {})[0])
        later = twice(frame)
        later.loc[later.index[-1], ["open", "high", "low", "close"]] = [100.7, 101.2, 100.6, 101.1]
        self.assertIsNotNone(self.signal(later, {})[0])

    def test_previous_day_and_forming_signal_are_not_entries(self):
        frame = _bars()
        for now in (frame.iloc[-1]["time"], frame.iloc[-1]["time"] + pd.Timedelta(days=1, minutes=1)):
            self.assertIsNone(self.signal(frame, {}, now)[0])

    def test_utc_and_eastern_have_same_signal(self):
        frame = _bars()
        expected, _ = self.signal(frame, {})
        frame["time"] = frame["time"].dt.tz_convert("UTC")
        actual, _ = self.signal(frame, {})
        self.assertEqual(expected.trigger_bar, actual.trigger_bar)
        self.assertEqual(expected.meta, actual.meta)

    def test_legacy_session_latch_does_not_block_fresh_setup(self):
        frame = twice(_bars())
        state = {"key": "TSLA:2026-08-12", "emitted": True}
        self.assertIsNotNone(self.signal(frame, state)[0])
        self.assertNotIn("emitted", state)

    def test_research_cohort_and_pending_captures_are_preserved(self):
        strategy = "V2_TSLA_TWO_LEG_TREND_PULLBACK"
        self.assertEqual("2.1.0.research.2", evidence_version(strategy, "2.2.0"))
        self.assertEqual({"2.1.0", "2.1.0.research.2", "2.2.0"}, set(capture_versions(strategy, "2.2.0")))
