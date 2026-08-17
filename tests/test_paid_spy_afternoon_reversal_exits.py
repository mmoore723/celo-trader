from datetime import datetime, timedelta
import unittest

from research.engine.exit_rules import planned_afternoon_reversal_exits
from research.engine.models import Bar, Side, Signal


def _bar(index: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        datetime(2026, 1, 2, 13, 0) + timedelta(minutes=5 * index),
        open_, high, low, close, 100,
    )


class AfternoonReversalExitTests(unittest.TestCase):
    def test_same_bar_stop_and_target_uses_conservative_stop(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 102, 99, 101),
            _bar(2, 101, 105, 95, 102),
        )
        signal = Signal("AFT", Side.LONG, bars[0].timestamp, 100, 96, 104)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual("structural_stop", plans["stop_target_60m"].reason)
        self.assertEqual(bars[2].timestamp + timedelta(minutes=5), plans["stop_target_60m"].time)

    def test_entry_candle_extremes_are_not_treated_as_post_fill_exit_events(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 105, 95, 101),
            _bar(2, 101, 102, 100, 101),
        )
        signal = Signal("AFT", Side.LONG, bars[0].timestamp, 100, 96, 104)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual("time_cap_60m", plans["stop_target_60m"].reason)

    def test_target_waits_until_completed_five_minute_bar(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 102, 99, 101),
            _bar(2, 101, 105, 100, 104),
        )
        signal = Signal("AFT", Side.LONG, bars[0].timestamp, 100, 96, 104)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual("two_r_target", plans["stop_target_60m"].reason)
        self.assertEqual(bars[2].timestamp + timedelta(minutes=5), plans["stop_target_60m"].time)

    def test_vwap_failure_requires_two_consecutive_completed_closes(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 101, 99, 100),
            _bar(2, 100, 100, 97, 98),
            _bar(3, 98, 99, 96, 97),
        )
        signal = Signal("AFT", Side.LONG, bars[0].timestamp, 100, 90, 110)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual("confirmed_vwap_failure", plans["vwap_failure_stop_target_60m"].reason)
        self.assertEqual(bars[3].timestamp + timedelta(minutes=5), plans["vwap_failure_stop_target_60m"].time)

    def test_short_same_bar_stop_and_target_uses_conservative_stop(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 101, 98, 99),
            _bar(2, 99, 105, 95, 98),
        )
        signal = Signal("AFT", Side.SHORT, bars[0].timestamp, 100, 104, 96)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual("structural_stop", plans["stop_target_60m"].reason)
        self.assertEqual(
            bars[2].timestamp + timedelta(minutes=5),
            plans["stop_target_60m"].time,
        )

    def test_short_vwap_failure_requires_two_consecutive_completed_closes(self) -> None:
        bars = (
            _bar(0, 100, 101, 99, 100),
            _bar(1, 100, 101, 99, 100),
            _bar(2, 100, 103, 100, 102),
            _bar(3, 102, 104, 101, 103),
        )
        signal = Signal("AFT", Side.SHORT, bars[0].timestamp, 100, 110, 90)
        plans = planned_afternoon_reversal_exits(bars, signal, bars[1])
        self.assertEqual(
            "confirmed_vwap_failure",
            plans["vwap_failure_stop_target_60m"].reason,
        )
        self.assertEqual(
            bars[3].timestamp + timedelta(minutes=5),
            plans["vwap_failure_stop_target_60m"].time,
        )

    def test_invalid_cap_and_missing_entry_are_rejected(self) -> None:
        bars = (_bar(0, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100))
        signal = Signal("AFT", Side.LONG, bars[0].timestamp, 100, 95, 105)
        with self.assertRaises(ValueError):
            planned_afternoon_reversal_exits(bars, signal, bars[1], cap_minutes=0)
        missing = _bar(9, 100, 101, 99, 100)
        with self.assertRaises(ValueError):
            planned_afternoon_reversal_exits(bars, signal, missing)


if __name__ == "__main__":
    unittest.main()
