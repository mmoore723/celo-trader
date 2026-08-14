"""Decision-gate tests for the TSLA two-leg configuration study."""
from datetime import date
import unittest

from research.jobs.tune_paid_tsla_two_leg_contexts import _partition, select_configuration


def _row(day: str, outcome: float) -> dict[str, object]:
    return {"signal_time": f"{day}T10:30:00-04:00", "return_pct": outcome}


class TwoLegTuningTests(unittest.TestCase):
    def test_training_and_later_partitions_are_disjoint_at_the_declared_cutoff(self) -> None:
        rows = [_row("2026-05-18", 1.0), _row("2026-05-19", 2.0)]
        self.assertEqual([rows[0]], _partition(rows, date(2026, 5, 19), True))
        self.assertEqual([rows[1]], _partition(rows, date(2026, 5, 19), False))

    def _marks(self, *, training: list[float], later: list[float]) -> dict[str, dict[int, list[dict[str, object]]]]:
        rows = [_row("2026-05-01", value) for value in training] + [_row("2026-06-01", value) for value in later]
        return {name: {hold: list(rows) for hold in (30, 60, 90)} for name in (
            "baseline", "stronger_impulse_1_50_atr", "shallow_pullback_0_25_to_0_75_atr", "stronger_impulse_and_shallow_pullback",
        )}

    def test_requires_positive_later_median_even_when_average_is_positive(self) -> None:
        marks = self._marks(training=[2.0] * 20, later=[20.0] + [-1.0] * 9)
        result = select_configuration(marks, date(2026, 5, 19))
        self.assertFalse(result["holdout_passed"])

    def test_selects_then_passes_when_both_untouched_measures_are_positive(self) -> None:
        marks = self._marks(training=[2.0] * 20, later=[1.0] * 10)
        result = select_configuration(marks, date(2026, 5, 19))
        self.assertEqual("baseline", result["selected_variant"])
        self.assertEqual(30, result["selected_hold_minutes"])
        self.assertTrue(result["holdout_passed"])

    def test_later_data_cannot_change_the_selected_training_configuration(self) -> None:
        """The later period is a verdict, never an input to the parameter choice."""
        baseline_training = [_row("2026-05-01", 2.0) for _ in range(20)]
        stronger_training = [_row("2026-05-01", 1.0) for _ in range(20)]
        later_a = [_row("2026-06-01", -3.0) for _ in range(10)]
        later_b = [_row("2026-06-01", 50.0) for _ in range(10)]
        variants = (
            "baseline", "stronger_impulse_1_50_atr",
            "shallow_pullback_0_25_to_0_75_atr", "stronger_impulse_and_shallow_pullback",
        )

        def marks(later: list[dict[str, object]]) -> dict[str, dict[int, list[dict[str, object]]]]:
            return {
                name: {
                    hold: list((baseline_training if name == "baseline" else stronger_training) + later)
                    for hold in (30, 60, 90)
                }
                for name in variants
            }

        bad_later = select_configuration(marks(later_a), date(2026, 5, 19))
        good_later = select_configuration(marks(later_b), date(2026, 5, 19))
        self.assertEqual("baseline", bad_later["selected_variant"])
        self.assertEqual("baseline", good_later["selected_variant"])
        self.assertFalse(bad_later["holdout_passed"])
        self.assertTrue(good_later["holdout_passed"])


if __name__ == "__main__":
    unittest.main()
