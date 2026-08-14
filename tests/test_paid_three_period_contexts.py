from datetime import date
import unittest

from research.jobs.assess_paid_three_period_contexts import assess


def row(day: str, side: str, value: float) -> dict[str, object]:
    return {"signal_time": f"{day}T10:30:00-04:00", "side": side, "return_pct": value}


class ThreePeriodContextTests(unittest.TestCase):
    def test_selects_only_when_all_three_periods_are_positive(self):
        rows = [
            *[row("2026-01-05", "long", 3.0) for _ in range(20)],
            *[row("2026-02-05", "long", 2.0) for _ in range(10)],
            *[row("2026-03-05", "long", 1.0) for _ in range(10)],
        ]
        result = assess(rows, selection_end=date(2026, 2, 1), validation_end=date(2026, 3, 1))
        self.assertEqual(result["decision"], "router_candidate")
        self.assertEqual(result["selected_context"], "all_signals")

    def test_rejects_when_selected_rule_fails_later(self):
        rows = [
            *[row("2026-01-05", "long", 3.0) for _ in range(20)],
            *[row("2026-02-05", "long", 2.0) for _ in range(10)],
            *[row("2026-03-05", "long", -1.0) for _ in range(10)],
        ]
        result = assess(rows, selection_end=date(2026, 2, 1), validation_end=date(2026, 3, 1))
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["later_passed"])

