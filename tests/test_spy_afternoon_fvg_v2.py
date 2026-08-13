from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

import strategies.spy_afternoon_fvg_v2 as afternoon_fvg
from strategies.market_structure import Bar


def _valid_bars(end_time: datetime = datetime(2026, 8, 10, 13, 30)) -> tuple[Bar, ...]:
    """Build a rising session with an upward FVG and its first retest."""
    start = end_time - timedelta(minutes=5 * 19)
    bars: list[Bar] = []
    for index in range(16):
        close = 100.0 + index * 0.10
        bars.append(Bar(start + timedelta(minutes=5 * index), close - 0.03, close + 0.08,
                        close - 0.09, close, 1_000.0))
    # Indices 16--18 form the three-bar upward imbalance. Index 19 is the
    # first later bar to overlap it and close in its favourable half.
    bars.extend((
        Bar(start + timedelta(minutes=80), 101.55, 101.70, 101.48, 101.60, 1_000.0),
        Bar(start + timedelta(minutes=85), 101.62, 102.55, 101.55, 102.40, 1_500.0),
        Bar(start + timedelta(minutes=90), 102.28, 102.38, 102.00, 102.22, 1_100.0),
        Bar(start + timedelta(minutes=95), 102.12, 102.22, 101.80, 102.06, 1_100.0),
    ))
    return tuple(bars)


class SpyAfternoonFvgV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        afternoon_fvg._emitted_trigger_by_session.clear()

    def test_exact_first_retest_rule_emits_spy_signal_in_reviewed_window(self) -> None:
        candidate = afternoon_fvg._signal_from_completed_bars(_valid_bars())

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual("V2_SPY_AFTERNOON_FVG", candidate.strategy_id)
        self.assertEqual("bullish", candidate.direction)
        self.assertEqual("upward_gap_retest", candidate.meta["trigger"])
        self.assertEqual(13, candidate.trigger_bar.hour)
        self.assertEqual(30, candidate.trigger_bar.minute)

    def test_rule_does_not_fire_outside_the_predeclared_afternoon_window(self) -> None:
        before_window = _valid_bars(datetime(2026, 8, 10, 13, 25))
        after_window = _valid_bars(datetime(2026, 8, 10, 15, 0))

        self.assertIsNone(afternoon_fvg._signal_from_completed_bars(before_window))
        self.assertIsNone(afternoon_fvg._signal_from_completed_bars(after_window))

    def test_live_adapter_is_spy_only_and_does_not_repeat_same_retest(self) -> None:
        frame = pd.DataFrame({
            "time": [datetime(2026, 8, 10, 13, 31)],
            "open": [102.1], "high": [102.2], "low": [102.0], "close": [102.1],
            "rvol": [1.3],
        })
        with patch.object(afternoon_fvg, "_complete_five_minute_bars", return_value=_valid_bars()):
            self.assertIsNone(afternoon_fvg.evaluate(frame, "QQQ"))
            first = afternoon_fvg.evaluate(frame, "SPY")
            second = afternoon_fvg.evaluate(frame, "SPY")

        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(1.3, first.rvol)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
