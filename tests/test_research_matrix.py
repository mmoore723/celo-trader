from contextlib import contextmanager
from datetime import datetime
import sqlite3
import unittest
from unittest.mock import patch

from strategy_health.research_matrix import _factor, build_research_matrix, research_status


class ResearchMatrixTests(unittest.TestCase):
    def test_profit_factor_uses_wins_over_absolute_losses(self):
        self.assertEqual(2.0, _factor([100, 50, -75]))
        self.assertEqual("infinite", _factor([10, 5]))
        self.assertIsNone(_factor([]))

    def test_plain_statuses_require_both_results_and_days(self):
        self.assertEqual("working", research_status(results=20, days=8, sessions=30, factor=1.5)[0])
        self.assertEqual("promising", research_status(results=5, days=2, sessions=30, factor=6.73)[0])
        self.assertEqual("needs_tuning", research_status(results=10, days=4, sessions=30, factor=1.2)[0])
        self.assertEqual("not_working", research_status(results=20, days=8, sessions=30, factor=0.9)[0])
        self.assertEqual("no_setups", research_status(results=0, days=0, sessions=20, factor=None)[0])

    def test_matrix_reads_only_the_active_account_and_real_option_marks(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE shadow_candidates (
                candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT,
                direction_correct INTEGER, directional_move_pct REAL, broker_account_id TEXT
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, bid REAL, ask REAL
            );
            CREATE TABLE scanner_candle_observations (
                ticker TEXT, bar_time TEXT, broker_account_id TEXT
            );
        """)
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?)", (
            "c1", "2026-09-03T10:00:00", "AAPL", "V2_SPY_AFTERNOON_FVG", 1, 1.2, "acct",
        ))
        conn.executemany("INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?)", [
            ("c1", "entry", 1.9, 2.0), ("c1", "mark_30m", 3.0, 3.1),
        ])
        conn.execute("INSERT INTO scanner_candle_observations VALUES (?,?,?)", (
            "AAPL", "2026-09-03T09:30:00", "acct",
        ))

        @contextmanager
        def connection():
            yield conn

        settings = {
            "active_broker_account_id": "acct", "watchlist": ["AAPL"],
            "research_strategy_ids": [],
        }
        with patch("config.get_settings", return_value=settings), patch(
            "database.get_conn", side_effect=connection,
        ), patch("database._now_et", return_value=datetime(2026, 9, 4, 12, 0)):
            matrix = build_research_matrix(90)
        row = next(item for item in matrix["strategies"] if item["strategy_id"] == "V2_SPY_AFTERNOON_FVG")
        pair = next(item for item in row["pairs"] if item["ticker"] == "AAPL")
        self.assertEqual(1, pair["option_results"])
        self.assertGreater(pair["net_one_contract_pnl"], 0)
        self.assertEqual(1, pair["market_days"])
        self.assertFalse(pair["tradable"])
        conn.close()

    def test_older_candidate_is_a_data_day_when_candle_archive_did_not_exist(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE shadow_candidates (
                candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT,
                direction_correct INTEGER, directional_move_pct REAL, broker_account_id TEXT
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, bid REAL, ask REAL
            );
            CREATE TABLE scanner_candle_observations (
                ticker TEXT, bar_time TEXT, broker_account_id TEXT
            );
        """)
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?)", (
            "older", "2026-08-10T10:00:00", "ABNB", "V2_SPY_AFTERNOON_FVG",
            None, None, "acct",
        ))

        @contextmanager
        def connection():
            yield conn

        settings = {
            "active_broker_account_id": "acct", "watchlist": ["SPY"],
            "research_strategy_ids": [],
        }
        with patch("config.get_settings", return_value=settings), patch(
            "database.get_conn", side_effect=connection,
        ), patch("database._now_et", return_value=datetime(2026, 9, 4, 12, 0)):
            matrix = build_research_matrix(90)
        row = next(item for item in matrix["strategies"] if item["strategy_id"] == "V2_SPY_AFTERNOON_FVG")
        pair = next(item for item in row["pairs"] if item["ticker"] == "ABNB")
        self.assertEqual(1, pair["market_days"])
        self.assertEqual("collecting", pair["status"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
