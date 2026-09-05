from contextlib import contextmanager
from datetime import datetime
import sqlite3
import unittest
from unittest.mock import patch

from strategy_health.research_matrix import (
    _chronological_factors, _current_rule_samples, _diagnosis, _exit_summary,
    _factor, _independent_samples, _quote_profit, build_research_matrix,
    research_status,
)


class ResearchMatrixTests(unittest.TestCase):
    def test_profit_factor_uses_wins_over_absolute_losses(self):
        self.assertEqual(2.0, _factor([100, 50, -75]))
        self.assertEqual("infinite", _factor([10, 5]))
        self.assertIsNone(_factor([]))

    def test_missing_exit_quote_is_not_invented_as_a_total_loss(self):
        row = {"entry_ask": 2.0, "bid_30": None}
        self.assertIsNone(_quote_profit(row, 30))
        row["bid_30"] = 3.0
        self.assertAlmostEqual(96.7, _quote_profit(row, 30))

    def test_late_quote_is_not_mislabeled_as_a_fixed_horizon_result(self):
        row = {
            "observed_at": "2026-09-03T10:00:00-04:00",
            "entry_ask": 2.0,
            "bid_30": 3.0,
            "entry_quote_at": "2026-09-03T10:00:01-04:00",
            "mark_30_at": "2026-09-03T10:41:00-04:00",
        }
        summary, profits = _exit_summary([row], 30)
        self.assertEqual([], profits)
        self.assertEqual(0, summary["option_results"])
        self.assertEqual(1, summary["mistimed_quotes_ignored"])

    def test_matrix_applies_current_rule_without_counting_old_unknown_rows(self):
        samples = [
            {"direction": "bullish", "metadata_json": '{"pa_consecutive_higher_lows": true}'},
            {"direction": "bullish", "metadata_json": '{"pa_consecutive_higher_lows": false}'},
            {"direction": "bullish", "metadata_json": "{}"},
        ]
        eligible, rejected, unscored = _current_rule_samples(
            samples, "V2_SPY_TREND_CONT", "SPY",
        )
        self.assertEqual(1, len(eligible))
        self.assertEqual(1, rejected)
        self.assertEqual(1, unscored)

    def test_independent_samples_collapse_same_trigger_and_holding_overlap(self):
        samples = [
            {"candidate_id": "first", "observed_at": "2026-09-04T10:01:00", "trigger_bar": "2026-09-04T10:00:00", "direction": "bullish"},
            {"candidate_id": "repeat", "observed_at": "2026-09-04T10:05:00", "trigger_bar": "2026-09-04T10:00:00", "direction": "bullish"},
            {"candidate_id": "overlap", "observed_at": "2026-09-04T10:11:00", "trigger_bar": "2026-09-04T10:10:00", "direction": "bearish"},
            {"candidate_id": "next", "observed_at": "2026-09-04T10:31:00", "trigger_bar": "2026-09-04T10:30:00", "direction": "bullish"},
        ]
        self.assertEqual(
            ["first", "next"],
            [row["candidate_id"] for row in _independent_samples(samples, 30)],
        )

    def test_plain_statuses_require_both_results_and_days(self):
        self.assertEqual("working", research_status(results=20, days=8, sessions=30, factor=1.5)[0])
        self.assertEqual("promising", research_status(results=5, days=2, sessions=30, factor=6.73)[0])
        self.assertEqual("collecting", research_status(results=1, days=1, sessions=30, factor="infinite")[0])
        self.assertEqual("losing_so_far", research_status(results=4, days=4, sessions=30, factor=0.0)[0])
        self.assertEqual("losing_so_far", research_status(results=5, days=5, sessions=30, factor=0.0)[0])
        self.assertEqual("needs_tuning", research_status(results=10, days=4, sessions=30, factor=1.2)[0])
        self.assertEqual("not_working", research_status(results=20, days=8, sessions=30, factor=0.9)[0])
        self.assertEqual("no_setups", research_status(results=0, days=0, sessions=20, factor=None)[0])

    def test_newer_dates_must_still_pass_before_a_pair_is_working(self):
        dated = []
        for day in range(1, 8):
            dated.extend([(f"2026-08-{day:02d}", 50.0)] * 2)
        for day in range(8, 11):
            dated.extend([(f"2026-08-{day:02d}", -10.0)] * 2)
        older, newer = _chronological_factors(dated)
        self.assertEqual("infinite", older)
        self.assertEqual(0.0, newer)
        status, message = research_status(
            results=20, days=10, sessions=30, factor=11.67,
            older_factor=older, newer_factor=newer,
        )
        self.assertEqual("needs_tuning", status)
        self.assertIn("newer dates", message)

    def test_diagnosis_points_to_an_exit_only_when_an_observed_exit_passes(self):
        diagnosis, action = _diagnosis(
            status="needs_tuning", setups=20, option_results=20,
            direction_results=20, direction_accuracy=60.0, factor=0.8,
            older_factor=None, newer_factor=None, exit_minutes=90,
            exit_summaries=[
                {"minutes": 30, "option_results": 20, "profit_factor": 1.7},
                {"minutes": 60, "option_results": 20, "profit_factor": 1.2},
                {"minutes": 90, "option_results": 20, "profit_factor": 0.8},
            ],
        )
        self.assertEqual("exit", diagnosis)
        self.assertIn("30-minute", action)

    def test_promising_option_result_is_not_overridden_by_other_horizon_direction(self):
        diagnosis, action = _diagnosis(
            status="promising", setups=20, option_results=18,
            direction_results=19, direction_accuracy=47.4, factor=15.25,
            older_factor=None, newer_factor=None, exit_minutes=30,
            exit_summaries=[
                {"minutes": 30, "option_results": 18, "profit_factor": 15.25},
                {"minutes": 60, "option_results": 13, "profit_factor": 4.36},
                {"minutes": 90, "option_results": 10, "profit_factor": 4.64},
            ],
        )
        self.assertEqual("more_data", diagnosis)
        self.assertIn("sample is too small", action)

    def test_matrix_reads_only_the_active_account_and_real_option_marks(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE shadow_candidates (
                candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT,
                direction_correct INTEGER, directional_move_pct REAL, broker_account_id TEXT,
                trigger_bar TEXT, direction TEXT, metadata_json TEXT
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, bid REAL, ask REAL,
                observed_at TEXT, source TEXT
            );
            CREATE TABLE candidate_contract_alternatives (
                candidate_id TEXT, contract_symbol TEXT, observation_kind TEXT,
                bid REAL, ask REAL, observed_at TEXT, policy_json TEXT, source TEXT
            );
            CREATE TABLE scanner_candle_observations (
                ticker TEXT, bar_time TEXT, broker_account_id TEXT
            );
        """)
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "c1", "2026-09-03T10:00:00", "AAPL", "V2_SPY_AFTERNOON_FVG", 1, 1.2, "acct",
            "2026-09-03T10:00:00", "bullish", "{}",
        ))
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "c2", "2026-09-03T11:00:00", "AAPL", "V2_SPY_AFTERNOON_FVG", 0, -0.4, "acct",
            "2026-09-03T11:00:00", "bearish", "{}",
        ))
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "other-user", "2026-09-03T12:00:00", "AAPL", "V2_SPY_AFTERNOON_FVG", 1, 2.0, "other",
            "2026-09-03T12:00:00", "bullish", "{}",
        ))
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "impulse", "2026-09-03T10:00:00", "AAPL",
            "V2_IMPULSE_ANCHORED_VWAP_PULLBACK", 1, 1.4, "acct",
            "2026-09-03T10:00:00", "bullish",
            '{"strategy_version":"research.1"}',
        ))
        conn.executemany("INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?)", [
            ("c1", "entry", 1.9, 2.0, "2026-09-03T10:00:00", "tradier_research_contract_v1"),
            ("c1", "mark_30m", 3.0, 3.1, "2026-09-03T10:30:00", "followup"),
            ("c2", "entry", 1.9, 2.0, "2026-09-03T11:00:00", "legacy_preview"),
            ("c2", "mark_30m", 9.0, 9.1, "2026-09-03T11:30:00", "followup"),
            ("other-user", "entry", 1.9, 2.0, "2026-09-03T12:00:00", "tradier_research_contract_v1"),
            ("other-user", "mark_30m", 9.0, 9.1, "2026-09-03T12:30:00", "followup"),
            ("impulse", "entry", 1.9, 2.0, "2026-09-03T10:00:00", "tradier_research_contract_v1"),
            ("impulse", "mark_120m", 3.0, 3.1, "2026-09-03T12:00:00", "followup"),
        ])
        conn.executemany("INSERT INTO candidate_contract_alternatives VALUES (?,?,?,?,?,?,?,?)", [
            ("c1", "AAPL_TEST", "entry", 1.9, 2.0, "2026-09-03T10:00:00", '["target_150_250"]', "tradier_research_contract_v1"),
            ("c1", "AAPL_TEST", "mark_30m", 3.0, 3.1, "2026-09-03T10:30:00", '["target_150_250"]', "tradier_alternative_followup"),
            ("other-user", "AAPL_OTHER", "entry", 1.9, 2.0, "2026-09-03T12:00:00", '["target_150_250"]', "tradier_research_contract_v1"),
            ("other-user", "AAPL_OTHER", "mark_30m", 9.0, 9.1, "2026-09-03T12:30:00", '["target_150_250"]', "tradier_alternative_followup"),
        ])
        conn.execute("INSERT INTO scanner_candle_observations VALUES (?,?,?)", (
            "AAPL", "2026-09-03T09:30:00", "acct",
        ))

        @contextmanager
        def connection():
            yield conn

        settings = {
            "active_broker_account_id": "acct", "watchlist": ["AAPL"],
            "research_strategy_ids": ["V2_IMPULSE_ANCHORED_VWAP_PULLBACK"],
        }
        with patch("config.get_settings", return_value=settings), patch(
            "database.get_conn", side_effect=connection,
        ), patch("database._now_et", return_value=datetime(2026, 9, 4, 12, 0)):
            matrix = build_research_matrix(90)
        row = next(item for item in matrix["strategies"] if item["strategy_id"] == "V2_SPY_AFTERNOON_FVG")
        pair = next(item for item in row["pairs"] if item["ticker"] == "AAPL")
        self.assertEqual(1, pair["option_results"])
        self.assertEqual(1, pair["option_result_days"])
        self.assertEqual(2, pair["setups"])
        self.assertEqual(50.0, pair["quote_coverage_pct"])
        self.assertEqual(1, pair["wins"])
        self.assertEqual(100.0, pair["win_rate_pct"])
        self.assertEqual(50.0, pair["direction_accuracy"])
        self.assertGreater(pair["net_one_contract_pnl"], 0)
        self.assertEqual(1, pair["market_days"])
        self.assertFalse(pair["tradable"])
        self.assertEqual("target_150_250", pair["leading_contract_test"]["policy"])
        self.assertEqual(1, pair["leading_contract_test"]["option_results"])
        self.assertEqual(1, pair["legacy_option_profiles_ignored"])
        impulse = next(
            item for item in matrix["strategies"]
            if item["strategy_id"] == "V2_IMPULSE_ANCHORED_VWAP_PULLBACK"
        )
        impulse_pair = next(item for item in impulse["pairs"] if item["ticker"] == "AAPL")
        self.assertEqual(120, impulse["exit_minutes"])
        self.assertEqual(1, impulse_pair["option_results"])
        self.assertEqual(100.0, impulse_pair["win_rate_pct"])
        self.assertGreater(impulse_pair["net_one_contract_pnl"], 0)
        self.assertEqual(
            1,
            next(
                result for result in impulse_pair["exit_comparison"]
                if result["minutes"] == 120
            )["option_results"],
        )
        conn.close()

    def test_older_candidate_is_a_data_day_when_candle_archive_did_not_exist(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE shadow_candidates (
                candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT,
                direction_correct INTEGER, directional_move_pct REAL, broker_account_id TEXT,
                trigger_bar TEXT, direction TEXT, metadata_json TEXT
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, bid REAL, ask REAL,
                observed_at TEXT, source TEXT
            );
            CREATE TABLE candidate_contract_alternatives (
                candidate_id TEXT, contract_symbol TEXT, observation_kind TEXT,
                bid REAL, ask REAL, observed_at TEXT, policy_json TEXT, source TEXT
            );
            CREATE TABLE scanner_candle_observations (
                ticker TEXT, bar_time TEXT, broker_account_id TEXT
            );
        """)
        conn.execute("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "older", "2026-08-10T10:00:00", "ABNB", "V2_SPY_AFTERNOON_FVG",
            None, None, "acct", "2026-08-10T10:00:00", "bullish", "{}",
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
