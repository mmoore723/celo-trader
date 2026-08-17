from __future__ import annotations

from datetime import date
import unittest

from research.engine.models import Side
from research.jobs.tune_paid_spy_afternoon_compression_context import context_flags, select_context


ALL_CONTEXTS = (
    "base", "rsi_aligned", "macd_aligned", "rsi_macd_aligned", "rsi_macd_not_extreme",
    "session_aligned", "session_aligned_rvol", "session_impulse", "session_impulse_rvol",
)


def row(day: str, return_pct: float) -> dict[str, object]:
    return {"signal_time": f"{day}T13:30:00-04:00", "return_pct": return_pct}


class PaidSpyAfternoonCompressionContextTests(unittest.TestCase):
    def test_directional_rsi_and_macd_flags_are_causal_and_symmetric(self) -> None:
        self.assertTrue(context_flags(Side.LONG, 60, .1)["rsi_macd_not_extreme"])
        self.assertTrue(context_flags(Side.SHORT, 40, -.1)["rsi_macd_not_extreme"])
        self.assertFalse(context_flags(Side.LONG, 75, .1)["rsi_macd_not_extreme"])
        self.assertFalse(context_flags(Side.SHORT, 40, .1)["macd_aligned"])

    def test_selection_requires_both_training_months_before_later_gate(self) -> None:
        may = [row(f"2026-05-{day:02d}", value) for day, value in enumerate((5, 4, 3, 2, 1, 2), 12)]
        june = [row(f"2026-06-{day:02d}", value) for day, value in enumerate((4, 3, 2, 1, 2, 3), 10)]
        july = [row(f"2026-07-{day:02d}", value) for day, value in enumerate((3, 2, 4, 1, 2, 3, 4, 2), 2)]
        rows = may + june + july
        flags = {str(item["signal_time"]): {name: True for name in ALL_CONTEXTS} for item in rows}
        result = select_context({"fixed_30m": rows}, flags, date(2026, 7, 1))
        self.assertEqual({"exit": "fixed_30m", "context": "base"}, result["selected"])
        self.assertTrue(result["later_data_passed"])

    def test_one_bad_training_month_cannot_be_hidden_by_the_other(self) -> None:
        may = [row(f"2026-05-{day:02d}", 5) for day in range(12, 18)]
        june = [row(f"2026-06-{day:02d}", -1) for day in range(10, 16)]
        rows = may + june
        flags = {str(item["signal_time"]): {name: True for name in ALL_CONTEXTS} for item in rows}
        result = select_context({"fixed_30m": rows}, flags, date(2026, 7, 1))
        self.assertIsNone(result["selected"])


if __name__ == "__main__":
    unittest.main()
