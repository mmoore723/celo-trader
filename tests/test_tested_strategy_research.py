from __future__ import annotations

from datetime import datetime, time, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar, Side, Signal as ResearchSignal
from research.engine.strategies import (
    AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig,
    LongOnlyRangeSweepReclaim, RangeSweepReclaimConfig,
)
from trading.tested_strategy_research import (
    DEFAULT_TESTED_RESEARCH_IDS, TESTED_RESEARCH_STRATEGIES,
    TestedResearchStrategy, enabled_tested_research_ids,
    _latest_candidate, _research_bars, evaluate_tested_research,
    public_tested_research_strategies,
)


class _AlwaysSignals:
    def evaluate(self, bars):
        current = bars[-1]
        return ResearchSignal(
            "TEST_RULE", Side.LONG, current.timestamp, current.close,
            current.close - 1, current.close + 2, {"proof": "completed"},
        )


class _SequentialSignals:
    def __init__(self):
        self.processed = 0

    def evaluate(self, bars):
        if len(bars) != self.processed + 1:
            raise ValueError("sequential bars required")
        self.processed += 1
        if bars[-1].close != 103:
            return None
        return ResearchSignal(
            "SEQUENTIAL", Side.LONG, bars[-1].timestamp, 103, 102, 105, {},
        )


class TestedStrategyResearchTests(unittest.TestCase):
    def test_every_rebuilt_strategy_is_on_by_default(self):
        self.assertEqual(set(TESTED_RESEARCH_STRATEGIES), enabled_tested_research_ids({}))
        self.assertEqual(set(TESTED_RESEARCH_STRATEGIES), set(DEFAULT_TESTED_RESEARCH_IDS))

    def test_unknown_saved_ids_cannot_become_runnable(self):
        self.assertEqual(
            {"V2_TREND_CONT"},
            enabled_tested_research_ids({"research_strategy_ids": ["V2_TREND_CONT", "MADE_UP"]}),
        )

    def test_new_rule_joins_accounts_with_every_prior_rule_enabled(self):
        prior_ids = set(DEFAULT_TESTED_RESEARCH_IDS) - {"V2_RANGE_SWEEP_RECLAIM"}
        self.assertIn(
            "V2_RANGE_SWEEP_RECLAIM",
            enabled_tested_research_ids({"research_strategy_ids": sorted(prior_ids)}),
        )

    def test_partial_saved_selection_does_not_enable_new_rule(self):
        self.assertEqual(
            {"V2_TREND_CONT"},
            enabled_tested_research_ids({"research_strategy_ids": ["V2_TREND_CONT"]}),
        )

    def test_public_rows_say_the_actual_research_scope(self):
        rows = public_tested_research_strategies({"research_strategy_ids": ["V2_TREND_CONT"]})
        row = next(item for item in rows if item["strategy_id"] == "V2_TREND_CONT")
        self.assertTrue(row["enabled"])
        self.assertEqual("all_collected_tickers", row["research_scope"])

    def test_one_minute_source_is_completed_and_resampled_per_strategy(self):
        start = datetime(2026, 9, 4, 9, 30)
        frame = pd.DataFrame({
            "time": [start + timedelta(minutes=index) for index in range(17)],
            "open": [100.0] * 17, "high": [101.0] * 17,
            "low": [99.0] * 17, "close": [100.5] * 17,
            "volume": [1000] * 17,
        })
        now = datetime(2026, 9, 4, 9, 46)
        one = _research_bars(frame, now, 1)
        five = _research_bars(frame, now, 5)
        fifteen = _research_bars(frame, now, 15)
        self.assertEqual(16, len(one))
        self.assertEqual([time(9, 30), time(9, 35), time(9, 40)], [bar.timestamp.time() for bar in five])
        self.assertEqual([time(9, 30)], [bar.timestamp.time() for bar in fifteen])
        self.assertEqual(time(9, 45), one[-1].timestamp.time())

    def test_sequential_rules_are_replayed_causally_and_stale_signals_are_rejected(self):
        start = datetime(2026, 9, 4, 10, 0)
        bars = tuple(
            Bar(start + timedelta(minutes=index), close, close + 1, close - 1, close, 1000)
            for index, close in enumerate((101, 102, 103))
        )
        signal = _latest_candidate(_SequentialSignals(), bars)
        self.assertIsNotNone(signal)
        stale = (*bars, Bar(start + timedelta(minutes=3), 104, 105, 103, 104, 1000))
        self.assertIsNone(_latest_candidate(_SequentialSignals(), stale))

    def test_rebuilt_signal_is_observation_only_and_deduped_per_ticker(self):
        spec = TestedResearchStrategy("TEST_RULE", "Test Rule", _AlwaysSignals)
        bar = Bar(datetime(2026, 9, 4, 10, 0), 100, 102, 99, 101, 1000)
        frame = pd.DataFrame({"close": [101.0]})
        with patch.dict(TESTED_RESEARCH_STRATEGIES, {"TEST_RULE": spec}, clear=True), patch(
            "trading.tested_strategy_research._research_bars", return_value=(bar,),
        ), patch("trading.tested_strategy_research._emitted", set()):
            first = evaluate_tested_research(frame, "AAPL", ["TEST_RULE"], scope="acct")
            second = evaluate_tested_research(frame, "AAPL", ["TEST_RULE"], scope="acct")
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertTrue(first[0].meta["observation_only"])
        self.assertEqual("2026-09-04 10:05:00", str(first[0].trigger_bar))

    def test_range_sweep_research_uses_tested_long_only_rule_and_30_minute_mark(self):
        spec = TESTED_RESEARCH_STRATEGIES["V2_RANGE_SWEEP_RECLAIM"]
        self.assertEqual(30, spec.exit_minutes)
        self.assertEqual(1, spec.timeframe_minutes)
        self.assertEqual(frozenset({Side.LONG}), spec.allowed_sides)
        self.assertEqual("RangeSweepReclaim", spec.factory().__class__.__name__)

    def test_new_rules_use_the_evidence_matched_configs_and_remain_research_only(self):
        compression = TESTED_RESEARCH_STRATEGIES["V2_AFTERNOON_COMPRESSION_BREAKOUT"]
        compression_rule = compression.factory()
        self.assertEqual(1, compression.timeframe_minutes)
        self.assertEqual(30, compression.exit_minutes)
        self.assertEqual(.004, compression_rule.config.max_compression_pct)
        self.assertEqual(time(15, 0), compression_rule.config.entry_end)
        impulse = TESTED_RESEARCH_STRATEGIES["V2_IMPULSE_ANCHORED_VWAP_PULLBACK"]
        impulse_rule = impulse.factory()
        self.assertEqual(5, impulse.timeframe_minutes)
        self.assertEqual(120, impulse.exit_minutes)
        self.assertEqual(.50, impulse_rule.config.stop_buffer_atr)
        self.assertEqual(2.0, impulse_rule.config.target_r)

    def test_impulse_rule_waits_for_a_completed_pullback_reclaim(self):
        spec = TESTED_RESEARCH_STRATEGIES["V2_IMPULSE_ANCHORED_VWAP_PULLBACK"]
        start = datetime(2026, 9, 4, 10, 0)
        bars = [
            Bar(start + timedelta(minutes=5 * index), 100, 100.10, 99.90, 100, 1000)
            for index in range(12)
        ]
        bars.append(Bar(start + timedelta(minutes=60), 100, 101.30, 99.90, 101.20, 2000))
        bars.append(Bar(start + timedelta(minutes=65), 101.10, 101.25, 100.80, 100.95, 1000))
        self.assertIsNone(_latest_candidate(spec.factory(), tuple(bars)))
        bars.append(Bar(start + timedelta(minutes=70), 100.90, 101.20, 100.75, 101.10, 1000))
        signal = _latest_candidate(spec.factory(), tuple(bars))
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(bars[-1].timestamp, signal.timestamp)

    def test_compression_rule_uses_only_the_frozen_box_before_the_break(self):
        start = datetime(2026, 9, 4, 12, 0)
        config = AfternoonCompressionBreakoutConfig(
            fast_ema=3, slow_ema=5, atr_bars=3, min_compression_bars=3,
            compression_start=time(12, 30), compression_end=time(12, 33),
            entry_end=time(13, 0), max_compression_pct=.01,
        )
        bars = [
            Bar(start + timedelta(minutes=index), close - .02, close + .04, close - .04, close, 1000)
            for index, close in enumerate((100.0, 100.1, 100.2, 100.25, 100.3, 100.35))
        ]
        box_start = datetime(2026, 9, 4, 12, 30)
        bars.extend(
            Bar(box_start + timedelta(minutes=index), close, 100.40, 100.32, close, 1000)
            for index, close in enumerate((100.35, 100.37, 100.36))
        )
        self.assertIsNone(_latest_candidate(AfternoonCompressionBreakout(config), tuple(bars)))
        bars.append(Bar(datetime(2026, 9, 4, 12, 33), 100.38, 100.58, 100.36, 100.55, 1000))
        signal = _latest_candidate(AfternoonCompressionBreakout(config), tuple(bars))
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("afternoon_compact_range_upward_expansion", signal.features["trigger"])

    def test_range_sweep_long_adapter_replays_the_session_and_emits_latest_call(self):
        start = datetime(2026, 1, 2, 10, 0)
        bars = []
        for index in range(21):
            close = 100.0 + (.08 if index % 2 else -.08)
            bars.append(Bar(
                start + timedelta(minutes=index), close,
                close + .10, close - .10, close, 1000,
            ))
        bars.extend((
            Bar(start + timedelta(minutes=21), 99.55, 99.62, 99.38, 99.48, 1000),
            Bar(start + timedelta(minutes=22), 99.50, 99.92, 99.45, 99.86, 1000),
        ))
        strategy = LongOnlyRangeSweepReclaim(RangeSweepReclaimConfig(
            range_bars=20, minimum_sweep_atr=.10, minimum_vwap_room_atr=.01,
            minimum_reward_risk=.05,
        ))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual(bars[-1].timestamp, signal.timestamp)


if __name__ == "__main__":
    unittest.main()
