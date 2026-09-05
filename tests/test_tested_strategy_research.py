from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar, Side, Signal as ResearchSignal
from research.engine.strategies import LongOnlyRangeSweepReclaim, RangeSweepReclaimConfig
from trading.tested_strategy_research import (
    DEFAULT_TESTED_RESEARCH_IDS, TESTED_RESEARCH_STRATEGIES,
    TestedResearchStrategy, enabled_tested_research_ids,
    evaluate_tested_research, public_tested_research_strategies,
)


class _AlwaysSignals:
    def evaluate(self, bars):
        current = bars[-1]
        return ResearchSignal(
            "TEST_RULE", Side.LONG, current.timestamp, current.close,
            current.close - 1, current.close + 2, {"proof": "completed"},
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
        self.assertEqual("LongOnlyRangeSweepReclaim", spec.factory().__class__.__name__)

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
