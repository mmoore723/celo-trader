from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from research.jobs.tune_paid_spy_afternoon_fvg_v2 import _first_eligible_one_minute_entry, _selection
from research.engine.models import Bar as ResearchBar
from research.engine.strategies import FairValueGap, FairValueGapConfig
from strategies.market_structure import Bar as LiveBar
from strategies.spy_afternoon_fvg_v2 import _signal_from_completed_bars


class PaidSpyAfternoonFvgEntryTimingTests(unittest.TestCase):
    def test_negative_training_rules_are_not_presented_as_selected(self) -> None:
        rows = [
            {
                "signal_time": f"2026-01-{day:02d}T13:34:00",
                "return_pct": -1.0,
            }
            for day in range(2, 17)
        ]
        result = _selection(
            {
                "live_baseline_0_50_atr": {30: rows, 60: [], 90: []},
                "stronger_gap_0_75_atr": {30: [], 60: [], 90: []},
                "strongest_gap_1_00_atr": {30: [], 60: [], 90: []},
            },
            datetime(2026, 2, 1).date(),
        )
        self.assertIsNone(result["selected_variant"])
        self.assertEqual("no_positive_training_configuration", result["reason"])

    def test_completed_five_minute_bar_enters_at_next_one_minute_open(self) -> None:
        # The 13:30 bucket contains 13:30…13:34; the bot can first trade at
        # 13:35.  The markout engine selects the first bar strictly after this
        # returned time, which is therefore the expected 13:35 entry bar.
        self.assertEqual(
            datetime(2026, 8, 10, 13, 34),
            _first_eligible_one_minute_entry(datetime(2026, 8, 10, 13, 30)),
        )

    def test_research_signal_premise_matches_live_spy_fvg_premise(self) -> None:
        # A fixed five-minute sequence that forms one upward imbalance and
        # then performs its first valid retest.  The paid-data job may tune
        # only its declared gap size; the baseline premise must otherwise
        # remain identical to the live adapter.
        start = datetime(2026, 8, 10, 11, 55)
        live: list[LiveBar] = []
        for index in range(16):
            close = 100.0 + index * 0.10
            live.append(LiveBar(start + timedelta(minutes=5 * index), close - 0.03, close + 0.08,
                                close - 0.09, close, 1_000.0))
        live.extend((
            LiveBar(start + timedelta(minutes=80), 101.55, 101.70, 101.48, 101.60, 1_000.0),
            LiveBar(start + timedelta(minutes=85), 101.62, 102.55, 101.55, 102.40, 1_500.0),
            LiveBar(start + timedelta(minutes=90), 102.28, 102.38, 102.00, 102.22, 1_100.0),
            LiveBar(start + timedelta(minutes=95), 102.12, 102.22, 101.80, 102.06, 1_100.0),
        ))
        research = tuple(ResearchBar(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in live)

        live_signal = _signal_from_completed_bars(tuple(live))
        research_signal = FairValueGap(FairValueGapConfig()).evaluate(research)

        self.assertIsNotNone(live_signal)
        self.assertIsNotNone(research_signal)
        assert live_signal is not None and research_signal is not None
        self.assertEqual("bullish", live_signal.direction)
        self.assertEqual("long", research_signal.side.value)
        self.assertEqual(live_signal.trigger_bar.to_pydatetime(), research_signal.timestamp)
        self.assertEqual(live_signal.meta["gap_lower"], research_signal.features["gap_lower"])
        self.assertEqual(live_signal.meta["gap_upper"], research_signal.features["gap_upper"])


if __name__ == "__main__":
    unittest.main()
