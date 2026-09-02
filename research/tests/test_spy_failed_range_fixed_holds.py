from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from research.jobs.assess_paid_spy_failed_range_fixed_holds import assess


def _row(day: str, entry: float, exit_bid: float, minute: int = 0) -> dict[str, object]:
    entered = datetime.fromisoformat(f"{day}T10:{minute:02d}:00-04:00")
    return {
        "signal_time": (entered - timedelta(minutes=1)).isoformat(),
        "entry_time": entered.isoformat(),
        "exit_time": (entered + timedelta(minutes=5)).isoformat(),
        "entry_ask": entry,
        "exit_bid": exit_bid,
    }


class FailedRangeFixedHoldAssessmentTests(unittest.TestCase):
    def test_promotes_only_one_hold_that_passes_all_three_periods(self) -> None:
        payload: dict[str, object] = {"complete": True, "markouts_by_hold": {}}
        periods = (("2026-05-04", 4), ("2026-06-02", 5), ("2026-07-02", 7))
        for hold in (5, 10, 15, 30):
            rows = []
            for day, count in periods:
                for index in range(count):
                    # The 5-minute rule alternates +$19.30/-$5.70 net, while
                    # the control and other candidates lose after costs.
                    exit_bid = 1.20 if hold == 5 and index % 2 == 0 else (0.95 if hold == 5 else 0.90)
                    rows.append(_row(day, 1.00, exit_bid, index * 6))
            payload["markouts_by_hold"][str(hold)] = rows
        result = assess(payload)
        self.assertEqual("promote_fixed_hold", result["decision"])
        self.assertEqual(5, result["selected_hold_minutes"])
        self.assertTrue(result["later_gates"]["holdout_july"]["passed"])

    def test_rejects_training_winner_that_fails_july(self) -> None:
        payload: dict[str, object] = {"complete": True, "markouts_by_hold": {}}
        for hold in (5, 10, 15, 30):
            rows = []
            for day, count in (("2026-05-04", 4), ("2026-06-02", 5), ("2026-07-02", 7)):
                for index in range(count):
                    if hold == 5 and not day.startswith("2026-07"):
                        exit_bid = 1.20 if index % 2 == 0 else 0.95
                    else:
                        exit_bid = 0.90
                    rows.append(_row(day, 1.00, exit_bid, index * 6))
            payload["markouts_by_hold"][str(hold)] = rows
        result = assess(payload)
        self.assertEqual("retain_fixed_30m", result["decision"])
        self.assertEqual(5, result["selected_hold_minutes"])
        self.assertFalse(result["later_gates"]["holdout_july"]["passed"])

    def test_rejects_incomplete_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            assess({"complete": False, "markouts_by_hold": {}})


if __name__ == "__main__":
    unittest.main()
