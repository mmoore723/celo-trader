from datetime import datetime, timedelta
import unittest

from research.jobs.assess_paid_breakout_pullback_volatility import (
    context_rows,
    select_context,
)


def row(day: int, hour: int, result: float, atr_pct: float) -> dict[str, object]:
    entry = datetime(2026, 5 if day < 20 else 7, day if day < 20 else day - 19, hour)
    return {
        "signal_time": entry.isoformat(),
        "entry_time": entry.isoformat(),
        "exit_time": (entry + timedelta(minutes=60)).isoformat(),
        "return_pct": result,
        "signal_atr_pct": atr_pct,
    }


class BreakoutPullbackVolatilityTests(unittest.TestCase):
    def test_context_filter_runs_before_position_capacity(self):
        first = row(1, 10, -20, .08)
        overlapping_quiet = row(1, 10, 4, .04)
        overlapping_quiet["entry_time"] = datetime(2026, 5, 1, 10, 30).isoformat()
        overlapping_quiet["exit_time"] = datetime(2026, 5, 1, 11, 30).isoformat()
        later_quiet = row(1, 12, 3, .04)
        later_quiet["entry_time"] = datetime(2026, 5, 1, 11, 30).isoformat()
        later_quiet["exit_time"] = datetime(2026, 5, 1, 12, 30).isoformat()
        rows = [first, overlapping_quiet, later_quiet]
        contexts = context_rows(rows)
        self.assertEqual(2, len(contexts["all_signals"]))
        self.assertEqual(.08, contexts["all_signals"][0]["signal_atr_pct"])
        self.assertEqual(2, len(contexts["quiet_atr_5bps"]))
        self.assertEqual(.04, contexts["quiet_atr_5bps"][0]["signal_atr_pct"])

    def test_training_selects_quiet_context_and_later_grades_it(self):
        rows = []
        for day in range(1, 11):
            rows.append(row(day, 10, 2, .04))
            rows.append(row(day, 12, -5, .08))
        for day in range(20, 30):
            rows.append(row(day, 10, 1, .04))
        result = select_context(context_rows(rows), datetime(2026, 7, 1).date())
        self.assertEqual("quiet_atr_5bps", result["selected_context"])
        self.assertTrue(result["later_data_passed"])


if __name__ == "__main__":
    unittest.main()
