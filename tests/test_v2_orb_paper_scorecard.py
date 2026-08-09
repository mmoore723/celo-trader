"""Tests for account-scoped prospective V2 paper evidence."""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import patch

from strategy_health.v2_orb_paper_scorecard import build_v2_orb_paper_scorecard


class V2OrbPaperScorecardTests(unittest.TestCase):
    def test_scopes_account_and_flags_nonmatching_exit(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE trades (
            strategy_id TEXT, paper INTEGER, broker_account_id TEXT, status TEXT,
            realized_pnl REAL, entry_price REAL, exit_price REAL, exit_reason TEXT)""")
        conn.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("V2_ORB_PULLBACK", 1, "paper:a", "closed", 20.0, 5.0, 5.2, "v2_orb_paid_markout_90m (held=90.0m)"),
            ("V2_ORB_PULLBACK", 1, "paper:a", "closed", -10.0, 5.0, 4.9, "manual_close"),
            ("V2_ORB_PULLBACK", 1, "paper:b", "closed", 99.0, 5.0, 5.99, "v2_orb_paid_markout_90m"),
        ])
        @contextmanager
        def fake_conn():
            yield conn
        with patch("strategy_health.v2_orb_paper_scorecard.get_conn", fake_conn):
            result = build_v2_orb_paper_scorecard(broker_account_id="paper:a")
        self.assertEqual(2, result["closed_trades"])
        self.assertEqual(1, result["wins"])
        self.assertEqual(1, result["study_matched_exits"])
        self.assertEqual(1, result["nonmatching_exits"])
        self.assertEqual("collecting_data", result["sample_status"])


if __name__ == "__main__":
    unittest.main()
