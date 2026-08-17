from datetime import date
import unittest

from research.jobs.compare_paid_spy_afternoon_reversal_exits import (
    EXIT_LABELS, comparable_markouts, select_exit,
)


def _row(day: str, number: int, value: float) -> dict[str, object]:
    return {
        "signal_time": f"{day}T13:{number:02d}:00",
        "entry_time": f"{day}T13:{number:02d}:00",
        "exit_time": f"{day}T13:{number + 1:02d}:00",
        "return_pct": value,
    }


class AfternoonReversalExitSelectionTests(unittest.TestCase):
    def test_comparable_markouts_use_shared_signal_ids(self) -> None:
        shared = _row("2026-01-02", 10, 2.0)
        rows = {label: [shared.copy()] for label in EXIT_LABELS}
        rows["fixed_30m"].append(_row("2026-01-03", 10, 4.0))
        result = comparable_markouts(rows)
        self.assertTrue(all(len(result[label]) == 1 for label in EXIT_LABELS))

    def test_training_selects_rule_but_later_data_can_reject_it(self) -> None:
        rows = {
            label: [
                _row("2026-01-02", index, 1.0)
                for index in range(10)
            ] + [
                _row("2026-07-02", index, 1.0)
                for index in range(10)
            ]
            for label in EXIT_LABELS
        }
        rows["stop_target_60m"] = [
            _row("2026-01-02", index, 3.0) for index in range(10)
        ] + [
            _row("2026-07-02", index, -1.0) for index in range(10)
        ]
        selected = select_exit(rows, date(2026, 7, 1))
        self.assertEqual("stop_target_60m", selected["selected_exit"])
        self.assertFalse(selected["later_data_passed"])
        self.assertEqual("no_exit_candidate_passed_holdout", selected["decision"])


if __name__ == "__main__":
    unittest.main()
