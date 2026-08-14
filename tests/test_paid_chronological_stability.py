from datetime import time
import unittest

from research.jobs.assess_paid_chronological_stability import assess_rows


def row(day: str, result: float, side: str = "long") -> dict[str, object]:
    return {"signal_time": f"{day}T13:30:00-05:00", "return_pct": result, "side": side}


def positioned_row(day: str, entry: str, exit_at: str, result: float) -> dict[str, object]:
    payload = row(day, result)
    payload.update({"entry_time": entry, "exit_time": exit_at})
    return payload


class PaidChronologicalStabilityTests(unittest.TestCase):
    def test_requires_positive_results_in_every_month(self):
        rows = [
            row("2026-05-02", 2), row("2026-05-03", 1),
            row("2026-06-02", 3), row("2026-06-03", 1),
            row("2026-07-02", 2), row("2026-07-03", 4),
        ]
        report = assess_rows(rows, start_time=time(13), end_time=time(14),
                             minimum_months=3, minimum_trades_per_month=2)
        self.assertEqual("stable_across_months", report["decision"])

    def test_one_bad_month_cannot_be_hidden_by_other_months(self):
        rows = [
            row("2026-05-02", -3), row("2026-05-03", -1),
            row("2026-06-02", 5), row("2026-06-03", 3),
            row("2026-07-02", 4), row("2026-07-03", 2),
        ]
        report = assess_rows(rows, minimum_months=3, minimum_trades_per_month=2)
        self.assertEqual("insufficient_or_inconsistent", report["decision"])
        self.assertIn("2026-05", " ".join(report["reasons"]))

    def test_one_position_policy_removes_overlapping_signal(self):
        rows = [
            positioned_row("2026-05-02", "2026-05-02T14:00:00+00:00",
                           "2026-05-02T20:00:00+00:00", 4),
            positioned_row("2026-05-02", "2026-05-02T15:00:00+00:00",
                           "2026-05-02T20:00:00+00:00", 100),
            positioned_row("2026-06-02", "2026-06-02T14:00:00+00:00",
                           "2026-06-02T20:00:00+00:00", 3),
        ]
        report = assess_rows(rows, minimum_months=2, minimum_trades_per_month=1,
                             one_position_at_a_time=True)
        self.assertEqual(3, report["signals_before_capacity"])
        self.assertEqual(2, report["trades_after_capacity"])
        self.assertEqual("one_open_position", report["fixed_context"]["position_policy"])
        self.assertEqual(4, report["months"][0]["average_return_pct"])


if __name__ == "__main__":
    unittest.main()
