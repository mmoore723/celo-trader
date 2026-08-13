"""Regression tests for the paid-data V2 ORB paper-validation exit."""
from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from trading.v2_orb_paper_exit import evaluate_v2_orb_paper_exit


class V2OrbPaperExitTests(unittest.TestCase):
    def test_holds_until_exact_paid_markout_window(self) -> None:
        entry = datetime(2026, 8, 3, 10, 40)
        self.assertEqual((False, "hold"), evaluate_v2_orb_paper_exit(entry, entry + timedelta(minutes=89, seconds=59)))
        should_exit, reason = evaluate_v2_orb_paper_exit(entry, entry + timedelta(minutes=90))
        self.assertTrue(should_exit)
        self.assertIn("v2_orb_paid_markout_90m", reason)

    def test_missing_entry_time_fails_closed(self) -> None:
        should_exit, reason = evaluate_v2_orb_paper_exit(None, datetime(2026, 8, 3, 12, 10))
        self.assertTrue(should_exit)
        self.assertEqual("v2_orb_missing_entry_time_safety", reason)

    def test_spy_trend_uses_its_reviewed_one_position_thirty_minute_exit(self) -> None:
        entry = datetime(2026, 8, 3, 10, 40)
        self.assertEqual(
            (False, "hold"),
            evaluate_v2_orb_paper_exit(entry, entry + timedelta(minutes=29, seconds=59), "V2_SPY_TREND_CONT"),
        )
        should_exit, reason = evaluate_v2_orb_paper_exit(
            entry, entry + timedelta(minutes=30), "V2_SPY_TREND_CONT",
        )
        self.assertTrue(should_exit)
        self.assertIn("v2_spy_trend_paid_markout_30m", reason)

    def test_spy_afternoon_fvg_uses_its_reviewed_thirty_minute_exit(self) -> None:
        entry = datetime(2026, 8, 3, 14, 0)
        self.assertEqual(
            (False, "hold"),
            evaluate_v2_orb_paper_exit(entry, entry + timedelta(minutes=29, seconds=59), "V2_SPY_AFTERNOON_FVG"),
        )
        should_exit, reason = evaluate_v2_orb_paper_exit(
            entry, entry + timedelta(minutes=30), "V2_SPY_AFTERNOON_FVG",
        )
        self.assertTrue(should_exit)
        self.assertIn("v2_spy_afternoon_fvg_paid_markout_30m", reason)

    def test_spy_afternoon_reversal_uses_its_reviewed_thirty_minute_exit(self) -> None:
        entry = datetime(2026, 8, 3, 13, 30)
        self.assertEqual(
            (False, "hold"),
            evaluate_v2_orb_paper_exit(entry, entry + timedelta(minutes=29, seconds=59), "V2_SPY_AFTERNOON_REVERSAL"),
        )
        should_exit, reason = evaluate_v2_orb_paper_exit(
            entry, entry + timedelta(minutes=30), "V2_SPY_AFTERNOON_REVERSAL",
        )
        self.assertTrue(should_exit)
        self.assertIn("v2_spy_afternoon_reversal_paid_markout_30m", reason)

    def test_tsla_noise_rule_uses_same_session_preclose_not_a_fake_duration(self) -> None:
        entry = datetime(2026, 8, 3, 10, 0)
        self.assertEqual(
            (False, "hold"),
            evaluate_v2_orb_paper_exit(entry, datetime(2026, 8, 3, 15, 58, 59), "V2_TSLA_NOISE_MOMENTUM"),
        )
        should_exit, reason = evaluate_v2_orb_paper_exit(
            entry, datetime(2026, 8, 3, 15, 59), "V2_TSLA_NOISE_MOMENTUM",
        )
        self.assertTrue(should_exit)
        self.assertIn("v2_tsla_noise_paid_markout_preclose_1559", reason)


if __name__ == "__main__":
    unittest.main()
