from datetime import date
import unittest

from research.jobs.summarize_paid_markouts_holdout import assess
from research.jobs.assess_paid_noise_momentum import assess as assess_noise


def row(day: str, result: float) -> dict[str, object]:
    return {"signal_time": f"{day}T10:00:00-05:00", "return_pct": result}


class PaidMarkoutHoldoutTests(unittest.TestCase):
    def test_positive_later_results_pass_the_fixed_rule(self):
        rows = [row("2026-02-01", -10)] + [row(f"2026-03-{day:02d}", 10 if day < 7 else -3) for day in range(1, 11)]
        report = assess(rows, date(2026, 3, 1))
        self.assertEqual("paper_candidate", report["decision"])
        self.assertEqual(10, report["holdout"]["trades"])

    def test_negative_later_results_cannot_pass_from_good_training(self):
        rows = [row(f"2026-02-{day:02d}", 20) for day in range(1, 12)] + [row(f"2026-03-{day:02d}", -4) for day in range(1, 11)]
        report = assess(rows, date(2026, 3, 1))
        self.assertEqual("reject", report["decision"])

    def test_too_few_later_results_rejects(self):
        rows = [row("2026-03-01", 20)] * 9
        self.assertEqual("reject", assess(rows, date(2026, 3, 1))["decision"])

    def test_noise_screen_requires_both_periods_to_clear_stricter_gate(self):
        rows = ([row("2026-02-02", 3 if item % 3 else -1) for item in range(1, 41)]
                + [row("2026-03-02", 2 if item % 3 else -1) for item in range(1, 21)])
        report = assess_noise(rows, holdout_start=date(2026, 3, 1))
        self.assertEqual("catalog_review_candidate", report["decision"])
        self.assertTrue(report["training_passed"])
        self.assertTrue(report["holdout_passed"])

    def test_noise_screen_rejects_positive_average_when_median_is_negative(self):
        rows = ([row("2026-02-02", 2) for _ in range(40)]
                + [row("2026-03-02", -1 if item < 12 else 15) for item in range(1, 21)])
        report = assess_noise(rows, holdout_start=date(2026, 3, 1))
        self.assertEqual("reject", report["decision"])
        self.assertIn("median return is not positive", report["holdout_reasons"])


if __name__ == "__main__":
    unittest.main()
