import unittest

from research.jobs.tune_paid_spy_afternoon_compression_confirmations import select_candidate


def rows(month: int, values: list[float]):
    return [
        {"signal_time": f"2026-{month:02d}-{index + 1:02d}T13:30:00-04:00", "return_pct": value}
        for index, value in enumerate(values)
    ]


class ConfirmationSelectionTests(unittest.TestCase):
    def test_selection_requires_both_training_months_then_checks_july(self) -> None:
        good = rows(5, [2, 2, 2, 2, -1]) + rows(6, [3, 3, 2, 2, -1]) + rows(7, [2] * 8)
        weak = rows(5, [-2] * 5) + rows(6, [4] * 5) + rows(7, [4] * 8)
        result = select_candidate({"hold_1m:fixed_30m": good, "retest_5m:fixed_30m": weak})
        self.assertEqual("hold_1m:fixed_30m", result["selected"])
        self.assertTrue(result["later_data_passed"])
        self.assertTrue(result["promote"])


if __name__ == "__main__":
    unittest.main()
