from datetime import date
import unittest

from research.jobs.compare_paid_rsi_macd_filters import (
    base_strategy,
    select_training_variant,
)


class PaidAfternoonReversalMomentumTests(unittest.TestCase):
    def test_afternoon_reversal_is_available_to_paid_confirmation_runner(self) -> None:
        self.assertEqual("V2_AFTERNOON_REVERSAL", base_strategy("afternoon_reversal").strategy_id)

    def test_small_paid_period_uses_explicit_sample_floors(self) -> None:
        def rows(day: str, value: float, count: int) -> list[dict[str, object]]:
            return [{"signal_time": f"{day}T13:15:00", "return_pct": value}] * count

        markouts = {
            "base": rows("2026-05-15", 1.0, 10) + rows("2026-07-02", 1.0, 8),
            "rsi_14_aligned": rows("2026-05-15", 2.0, 10) + rows("2026-07-02", -1.0, 8),
            "macd_12_26_9_aligned": [],
            "rsi_and_macd_aligned": [],
        }
        result = select_training_variant(
            markouts, date(2026, 7, 1),
            minimum_training_signals=10, minimum_later_signals=8,
        )
        self.assertEqual("rsi_14_aligned", result["selected_variant"])
        self.assertFalse(result["later_data_passed"])
        self.assertEqual(10, result["minimum_training_signals"])
        self.assertEqual(8, result["minimum_later_signals"])


if __name__ == "__main__":
    unittest.main()
