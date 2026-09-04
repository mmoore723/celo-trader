from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar, Side, Signal as ResearchSignal
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


if __name__ == "__main__":
    unittest.main()
