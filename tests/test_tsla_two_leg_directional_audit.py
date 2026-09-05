from __future__ import annotations

from datetime import date
import unittest

from research.jobs.audit_tsla_two_leg_directional_repair import _partition, summarize


class TslaTwoLegDirectionalAuditTests(unittest.TestCase):
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

    def test_holdout_partition_never_moves_cutoff_day_into_older_data(self) -> None:
        rows = [
            {"signal_time": "2026-05-18T10:00:00-04:00"},
            {"signal_time": "2026-05-19T10:00:00-04:00"},
        ]

        self.assertEqual([rows[0]], _partition(rows, date(2026, 5, 19), True))
        self.assertEqual([rows[1]], _partition(rows, date(2026, 5, 19), False))


if __name__ == "__main__":
    unittest.main()
