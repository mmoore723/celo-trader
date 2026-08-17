from __future__ import annotations

from datetime import date
import unittest

from research.jobs.assess_paid_tsla_range_sweep_transfer import _decision


def _rows(start_month: int, count: int, value: float):
    return [
        {
            "signal_time": f"2026-{start_month:02d}-{(index % 25) + 1:02d}T11:00:00-04:00",
            "return_pct": value,
        }
        for index in range(count)
    ]


class PaidTslaRangeSweepTransferTests(unittest.TestCase):
    def test_portable_lead_requires_both_periods(self):
        rows = _rows(1, 20, 2.0) + _rows(4, 10, 1.0)
        result = _decision(rows, date(2026, 3, 1))
        self.assertTrue(result["passed"])
        self.assertEqual("portable_lead", result["decision"])

    def test_negative_later_period_fails(self):
        rows = _rows(1, 20, 2.0) + _rows(4, 10, -1.0)
        result = _decision(rows, date(2026, 3, 1))
        self.assertFalse(result["passed"])
        self.assertEqual("not_portable", result["decision"])

    def test_too_few_later_trades_fails(self):
        rows = _rows(1, 20, 2.0) + _rows(4, 9, 1.0)
        self.assertFalse(_decision(rows, date(2026, 3, 1))["passed"])


if __name__ == "__main__":
    unittest.main()
