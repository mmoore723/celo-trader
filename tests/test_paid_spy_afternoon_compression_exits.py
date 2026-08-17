from __future__ import annotations

from datetime import date, datetime
import unittest

from research.engine.models import Bar, Side, Signal
from research.jobs.tune_paid_spy_afternoon_compression_exits import (
    EXIT_LABELS, exit_plans_for_signals, select_exit,
)


def row(day: str, value: float) -> dict[str, object]:
    return {"signal_time": f"{day}T13:00:00-04:00", "return_pct": value}


class PaidSpyAfternoonCompressionExitTests(unittest.TestCase):
    def test_exit_selection_uses_earlier_data_then_checks_later(self) -> None:
        markouts = {label: [] for label in EXIT_LABELS}
        markouts["fixed_30m"] = [row("2026-06-01", 5)] * 15 + [row("2026-07-01", -2)] * 10
        markouts["confirmed_vwap_ema_60m"] = [row("2026-06-01", 3)] * 15 + [row("2026-07-01", 2)] * 10
        result = select_exit(markouts, date(2026, 7, 1))
        self.assertEqual("fixed_30m", result["selected_exit"])
        self.assertFalse(result["later_data_passed"])

    def test_exit_plans_are_causal_and_include_fixed_baselines(self) -> None:
        bars = tuple(
            Bar(datetime(2026, 6, 1, 13, minute), 100, 101, 99, 100, 1000)
            for minute in range(20)
        )
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 98, 104, {})
        plans = exit_plans_for_signals(bars, (signal,))
        self.assertEqual(set(EXIT_LABELS), set(plans))
        self.assertEqual(bars[1].timestamp, signal.timestamp.replace(minute=1))
        self.assertEqual(bars[1].timestamp.replace(minute=31), plans["fixed_30m"][signal.timestamp].time)


if __name__ == "__main__":
    unittest.main()
