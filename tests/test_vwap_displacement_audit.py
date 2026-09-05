from __future__ import annotations

import unittest

from research.jobs.audit_vwap_displacement_parity import _cohort, summarize


class VwapDisplacementAuditTests(unittest.TestCase):
    def test_summary_uses_after_cost_dollars_for_profit_factor(self) -> None:
        result = summarize([
            {"net_pnl_one_contract": 30.0, "net_return_pct": 3.0},
            {"net_pnl_one_contract": -10.0, "net_return_pct": -1.0},
            {"net_pnl_one_contract": 10.0, "net_return_pct": 1.0},
            {"net_pnl_one_contract": -10.0, "net_return_pct": -1.0},
        ])

        self.assertEqual(4, result["trades"])
        self.assertEqual(2, result["wins"])
        self.assertEqual(2.0, result["profit_factor"])
        self.assertEqual(20.0, result["net_pnl_one_contract"])

    def test_chronological_boundaries_are_not_moved_backwards(self) -> None:
        validation = "2026-01-30"
        later = "2026-05-01"
        self.assertEqual("selection", _cohort("2026-01-29T15:00:00-05:00", validation, later))
        self.assertEqual("validation", _cohort("2026-01-30T15:00:00-05:00", validation, later))
        self.assertEqual("later", _cohort("2026-05-01T15:00:00-04:00", validation, later))


if __name__ == "__main__":
    unittest.main()
