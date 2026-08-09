"""Regression tests for paid-study-equivalent V2 paper order prices."""
from __future__ import annotations

import unittest

from trading.v2_orb_paper_execution import entry_limit_prices, exit_limit_prices, include_tsla_when_v2_pilot_enabled


class V2OrbPaperExecutionTests(unittest.TestCase):
    def test_v2_paper_crosses_to_ask_and_bid_without_midpoint_improvement(self) -> None:
        self.assertEqual((5.10, None), entry_limit_prices(ask=5.10, midpoint=5.00, v2_paper_pilot=True))
        self.assertEqual((4.90, None), exit_limit_prices(bid=4.90, midpoint=5.00, v2_paper_pilot=True))

    def test_normal_execution_keeps_midpoint_then_spread_crossing(self) -> None:
        self.assertEqual((5.00, 5.10), entry_limit_prices(ask=5.10, midpoint=5.00, v2_paper_pilot=False))
        self.assertEqual((5.00, 4.90), exit_limit_prices(bid=4.90, midpoint=5.00, v2_paper_pilot=False))

    def test_tsla_is_added_only_for_an_explicit_v2_paper_pilot(self) -> None:
        original = ["SPY", "qqq", "SPY"]
        self.assertEqual(["SPY", "QQQ"], include_tsla_when_v2_pilot_enabled(original, v2_paper_pilot=False))
        self.assertEqual(["SPY", "QQQ", "TSLA"], include_tsla_when_v2_pilot_enabled(original, v2_paper_pilot=True))


if __name__ == "__main__":
    unittest.main()
