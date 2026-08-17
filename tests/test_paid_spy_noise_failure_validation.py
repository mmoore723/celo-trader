import unittest
from datetime import date

from research.jobs.validate_paid_spy_noise_failure_exits import _rows_before_month
from research.jobs.validate_paid_spy_noise_failure_momentum import assess, score


def _row(day: str, value: float, minute: int = 0):
    return {
        "entry_time": f"{day}T15:{minute:02d}:00+00:00",
        "return_pct": value,
    }


class PaidSpyNoiseFailureValidationTests(unittest.TestCase):
    def test_score_reports_robust_distribution_statistics(self):
        result = score([-2.0, 1.0, 3.0, 8.0])
        self.assertEqual(result["trades"], 4)
        self.assertEqual(result["average_return_pct"], 2.5)
        self.assertEqual(result["median_return_pct"], 2.0)
        self.assertEqual(result["profit_factor"], 6.0)
        self.assertEqual(result["iqr_pct"], 4.0)
        self.assertIsNotNone(result["bootstrap_mean_95pct_ci"])

    def test_assessment_enforces_one_open_position_per_session(self):
        rows = [
            _row("2026-05-12", 4.0, 1),
            _row("2026-05-12", 40.0, 30),
            _row("2026-05-13", -1.0, 1),
        ]
        result = assess(rows)
        self.assertEqual(result["raw_executable_signals"], 3)
        self.assertEqual(result["trades_after_one_position_capacity"], 2)
        self.assertEqual(result["overall"]["total_return_pct"], 3.0)

    def test_assessment_rejects_outlier_dependent_candidate(self):
        rows = []
        for month in ("05", "06", "07"):
            for day, value in enumerate(
                (50.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0), start=1,
            ):
                rows.append(_row(f"2026-{month}-{day:02d}", value))
        result = assess(rows)
        self.assertEqual(result["decision"], "reject")
        self.assertIn(
            "result did not survive removal of its single best trade",
            result["reasons"],
        )

    def test_exit_repair_keeps_only_baseline_rows_after_may(self):
        rows = [
            {"signal_time": "2026-05-29T10:00:00-04:00", "return_pct": 1.0},
            {"signal_time": "2026-06-01T10:00:00-04:00", "return_pct": 2.0},
            {"signal_time": "2026-07-01T10:00:00-04:00", "return_pct": 3.0},
        ]
        kept = _rows_before_month(rows, date(2026, 6, 1))
        self.assertEqual([row["return_pct"] for row in kept], [2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
