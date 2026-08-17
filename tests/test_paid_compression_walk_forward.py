from __future__ import annotations

import unittest

from research.jobs.summarize_paid_compression_walk_forward import (
    build_report,
    causal_month_folds,
    summarize,
)


def row(day: str, value: float) -> dict[str, object]:
    return {"signal_time": f"{day}T13:30:00-04:00", "return_pct": value}


class PaidCompressionWalkForwardTests(unittest.TestCase):
    def test_summary_reports_robust_center_and_profit_factor(self) -> None:
        result = summarize([row("2026-05-01", 10), row("2026-05-02", -5), row("2026-05-03", 2)])
        self.assertEqual(3, result["trades"])
        self.assertEqual(2, result["wins"])
        self.assertEqual(2.0, result["median_return_pct"])
        self.assertEqual(2.4, result["profit_factor"])

    def test_month_selection_never_reads_the_test_month(self) -> None:
        markouts = {
            "stable": [
                *(row(f"2026-05-{day:02d}", 2) for day in range(1, 5)),
                *(row(f"2026-06-{day:02d}", 1) for day in range(1, 4)),
            ],
            "future_star": [
                *(row(f"2026-05-{day:02d}", -1) for day in range(1, 5)),
                *(row(f"2026-06-{day:02d}", 100) for day in range(1, 4)),
            ],
        }
        june = causal_month_folds(markouts)[0]
        self.assertEqual("2026-06", june["test_month"])
        self.assertEqual("stable", june["selected_variant"])
        self.assertTrue(june["passed"])

    def test_report_does_not_promote_from_one_evaluated_fold(self) -> None:
        source = {
            "complete": True,
            "markouts_by_variant": {
                "stable": [
                    *(row(f"2026-05-{day:02d}", 2) for day in range(1, 5)),
                    *(row(f"2026-06-{day:02d}", 1) for day in range(1, 4)),
                ],
            },
        }
        report = build_report(source, bootstrap_samples=100)
        self.assertFalse(report["decision"]["promote"])
        self.assertEqual("insufficient_independent_walk_forward_folds", report["decision"]["reason"])


if __name__ == "__main__":
    unittest.main()
