from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from research.jobs.rebuild_spy_trend_deployed_cohort import (
    replay_session_signals,
    summarize,
)
from strategies.market_structure import Bar, Side, StructureSignal


class SpyTrendDeployedCohortTests(unittest.TestCase):
    def test_replay_suppresses_one_breakout_then_rearms_after_level_cross(self) -> None:
        start = datetime(2026, 8, 10, 9, 30)
        bars = [
            Bar(start + timedelta(minutes=5 * index), 100.0, 102.0, 99.0, 101.0)
            for index in range(23)
        ]
        # The 11:15 candle is still above the first broken level, while the
        # 11:10 candle closes back through it and re-arms the 11:20 breakout.
        bars[21] = Bar(bars[21].timestamp, 100.0, 101.0, 98.0, 99.0)
        signals = {
            bars[19].timestamp: StructureSignal(
                Side.LONG, bars[19].timestamp, 101.0, 100.0, 103.0,
                {"prior_high": 100.0, "pa_consecutive_higher_lows": True},
            ),
            bars[20].timestamp: StructureSignal(
                Side.LONG, bars[20].timestamp, 101.0, 100.0, 103.0,
                {"prior_high": 100.5, "pa_consecutive_higher_lows": True},
            ),
            bars[22].timestamp: StructureSignal(
                Side.LONG, bars[22].timestamp, 101.0, 100.0, 103.0,
                {"prior_high": 100.5, "pa_consecutive_higher_lows": True},
            ),
        }

        raw, emitted = replay_session_signals(
            bars, evaluator=lambda history: signals.get(history[-1].timestamp),
        )

        self.assertEqual(3, len(raw))
        self.assertEqual(2, len(emitted))
        self.assertNotIn((bars[20].timestamp.isoformat(), "long"), emitted)
        self.assertIn((bars[22].timestamp.isoformat(), "long"), emitted)

    def test_summary_distinguishes_raw_quote_wins_from_after_cost_wins(self) -> None:
        rows = [
            {"entry_ask": 1.00, "exit_bid": 1.01},
            {"entry_ask": 1.00, "exit_bid": 1.10},
            {"entry_ask": 1.00, "exit_bid": 0.90},
        ]

        result = summarize(rows)

        self.assertEqual(2, result["raw_quote_wins_before_costs"])
        self.assertEqual(1, result["wins_after_costs"])
        self.assertEqual(-5.72, result["net_pnl_one_contract_after_costs"])


if __name__ == "__main__":
    unittest.main()
