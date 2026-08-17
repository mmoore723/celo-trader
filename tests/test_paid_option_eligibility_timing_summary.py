from __future__ import annotations

import unittest

from research.jobs.summarize_paid_option_eligibility_timing import build_report


def signal(day: str, entry: float, exit_bid: float, delay: float = 120) -> dict[str, object]:
    return {
        "signal_time": f"{day}T13:00:00-04:00",
        "selected_contract": "SPY TEST",
        "selected_ask": entry,
        "exit_quote_found": delay <= 60,
        "first_exit_quote_delay_seconds": delay,
        "first_exit_bid": exit_bid,
    }


class PaidOptionEligibilityTimingSummaryTests(unittest.TestCase):
    def test_requires_complete_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be complete"):
            build_report({"complete": False, "signals": []})

    def test_requires_both_earlier_and_later_profitability(self) -> None:
        earlier = [signal(f"2026-06-{day:02d}", 1, 1.1) for day in range(1, 11)]
        later = [signal(f"2026-07-{day:02d}", 1, 1.1) for day in range(1, 6)]
        report = build_report({"complete": True, "signals": earlier + later})
        self.assertEqual("ready_for_execution_model_comparison", report["decision"]["outcome"])
        self.assertFalse(report["decision"]["promote"])
        self.assertTrue(all(report["decision"]["gates"].values()))

        losing_later = [signal(f"2026-07-{day:02d}", 1, .9) for day in range(1, 6)]
        failed = build_report({"complete": True, "signals": earlier + losing_later})
        self.assertEqual("bounded_exit_not_robust", failed["decision"]["outcome"])
        self.assertFalse(failed["decision"]["gates"]["later_period_profitable"])

    def test_does_not_count_quotes_after_five_minute_bound(self) -> None:
        rows = [signal(f"2026-06-{day:02d}", 1, 1.1, delay=600) for day in range(1, 16)]
        report = build_report({"complete": True, "signals": rows})
        self.assertEqual(0, report["coverage"]["bounded_entry_exit_pairs"])
        self.assertEqual("historical_exit_quote_coverage_insufficient", report["decision"]["outcome"])


if __name__ == "__main__":
    unittest.main()
