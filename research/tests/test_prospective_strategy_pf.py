from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.jobs.audit_prospective_strategy_pf import analyze


class ProspectiveStrategyPfTests(unittest.TestCase):
    def test_clusters_repeated_candidates_and_freezes_first_quote(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "episodes.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE shadow_candidates (
                    candidate_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT,
                    strategy_id TEXT, direction TEXT, trigger_bar TEXT, final_outcome TEXT,
                    linked_trade_id INTEGER
                );
                CREATE TABLE candidate_option_quote_observations (
                    candidate_id TEXT, observed_at TEXT, observation_kind TEXT,
                    contract_symbol TEXT, bid REAL, ask REAL, source TEXT
                );
            """)
            candidates = [
                ("first", "2026-08-01T10:00:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "observed_only", None),
                ("repeat", "2026-08-01T10:01:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "entered", 7),
                ("stale-repeat", "2026-08-01T10:10:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "entered", 8),
                ("overlap", "2026-08-01T10:20:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bearish", "2026-08-01 10:15:00", "blocked", None),
                ("later", "2026-08-01T10:30:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 10:25:00", "blocked", None),
                ("wrong-ticker", "2026-08-01T11:30:00-04:00", "TSLA", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 11:25:00", "observed_only", None),
            ]
            conn.executemany("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?)", candidates)
            quotes = [
                ("first", candidates[0][1], "entry", "SPY-C", 0.99, 1.00, "tradier_preview"),
                ("first", "2026-08-01T10:30:00-04:00", "mark_30m", "SPY-C", 1.10, 1.11, "tradier_followup"),
                ("repeat", candidates[1][1], "entry", "SPY-C", 0.99, 1.00, "tradier_preview"),
                ("repeat", "2026-08-01T10:31:00-04:00", "mark_30m", "SPY-C", 9.00, 9.01, "tradier_followup"),
                ("stale-repeat", candidates[2][1], "entry", "SPY-C", 0.99, 1.00, "tradier_preview"),
                ("stale-repeat", "2026-08-01T10:40:00-04:00", "mark_30m", "SPY-C", 9.00, 9.01, "tradier_followup"),
                ("overlap", candidates[3][1], "entry", "SPY-O", 0.99, 1.00, "tradier_preview"),
                ("overlap", "2026-08-01T10:50:00-04:00", "mark_30m", "SPY-O", 5.00, 5.01, "tradier_followup"),
                ("later", candidates[4][1], "entry", "SPY-P", 0.99, 1.00, "tradier_preview"),
                ("later", "2026-08-01T11:00:00-04:00", "mark_30m", "SPY-P", 0.90, 0.91, "tradier_followup"),
                ("wrong-ticker", candidates[5][1], "entry", "TSLA-C", 0.99, 1.00, "tradier_preview"),
                ("wrong-ticker", "2026-08-01T12:00:00-04:00", "mark_30m", "TSLA-C", 9.00, 9.01, "tradier_followup"),
            ]
            conn.executemany("INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?,?)", quotes)
            conn.commit()
            conn.close()

            report = analyze(path, fee_per_contract_per_side=0, slippage_price_per_side=0)
            self.assertEqual(6, report["raw_candidates"])
            self.assertEqual(4, report["eligible_reviewed_scope_candidates"])
            self.assertEqual(1, report["excluded_candidate_reasons"]["ticker_outside_reviewed_scope"])
            self.assertEqual(1, report["excluded_candidate_reasons"]["expired_or_replayed_signal"])
            self.assertEqual(1, report["overlapping_setups_skipped"])
            self.assertEqual(2, report["independent_episodes"])
            self.assertEqual(2, report["measured_episodes"])
            details = report["by_strategy"]["V2_SPY_TREND_CONT"]["episodes_detail"]
            self.assertEqual(["first", "later"], [row["candidate_id"] for row in details])
            self.assertEqual(10.0, details[0]["net_return_pct"])
            self.assertEqual(10.0, details[0]["net_pnl_one_contract"])
            self.assertTrue(details[0]["episode_had_entered_trade"])
            account = report["account_level_replay"]
            self.assertEqual(2, account["account_trades"])
            self.assertEqual(0, account["skip_counts"].get("ticker_position_open", 0))
            self.assertFalse(account["gates"]["same_broker_order_fill_parity"])
            self.assertFalse(account["launch_ready"])

    def test_missing_first_followup_does_not_select_later_repeat(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE shadow_candidates (
                    candidate_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT,
                    strategy_id TEXT, direction TEXT, trigger_bar TEXT, final_outcome TEXT,
                    linked_trade_id INTEGER
                );
                CREATE TABLE candidate_option_quote_observations (
                    candidate_id TEXT, observed_at TEXT, observation_kind TEXT,
                    contract_symbol TEXT, bid REAL, ask REAL, source TEXT
                );
            """)
            conn.executemany("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?)", [
                ("first", "2026-08-01T10:00:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "blocked", None),
                ("repeat", "2026-08-01T10:05:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "entered", 9),
            ])
            conn.executemany("INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?,?)", [
                ("first", "2026-08-01T10:00:00-04:00", "entry", "SPY-C", .99, 1.0, "tradier_preview"),
                ("repeat", "2026-08-01T10:05:00-04:00", "entry", "SPY-C", .99, 1.0, "tradier_preview"),
                ("repeat", "2026-08-01T10:35:00-04:00", "mark_30m", "SPY-C", 2.0, 2.01, "tradier_followup"),
            ])
            conn.commit()
            conn.close()

            report = analyze(path)
            self.assertEqual(0, report["measured_episodes"])
            self.assertEqual(1, report["unmeasured_episode_reasons"]["missing_mark_30m"])
            self.assertEqual(0, report["account_level_replay"]["account_trades"])

    def test_account_replay_removes_cross_strategy_same_ticker_overlap(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE shadow_candidates (
                    candidate_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT,
                    strategy_id TEXT, direction TEXT, trigger_bar TEXT, final_outcome TEXT,
                    linked_trade_id INTEGER
                );
                CREATE TABLE candidate_option_quote_observations (
                    candidate_id TEXT, observed_at TEXT, observation_kind TEXT,
                    contract_symbol TEXT, bid REAL, ask REAL, source TEXT
                );
            """)
            candidates = [
                ("trend", "2026-08-01T10:00:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bullish", "2026-08-01 09:55:00", "observed_only", None),
                ("failed", "2026-08-01T10:10:00-04:00", "SPY", "V2_FAILED_OR_BREAK_VWAP_REVERSION", "bullish", "2026-08-01 10:09:00", "observed_only", None),
            ]
            conn.executemany("INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?)", candidates)
            conn.executemany("INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?,?)", [
                ("trend", candidates[0][1], "entry", "SPY-C", .99, 1.0, "tradier_preview"),
                ("trend", "2026-08-01T10:30:00-04:00", "mark_30m", "SPY-C", 1.1, 1.11, "tradier_followup"),
                ("failed", candidates[1][1], "entry", "SPY-F", .99, 1.0, "tradier_preview"),
                ("failed", "2026-08-01T10:40:00-04:00", "mark_30m", "SPY-F", 2.0, 2.01, "tradier_followup"),
            ])
            conn.commit()
            conn.close()

            report = analyze(path, fee_per_contract_per_side=0, slippage_price_per_side=0)
            account = report["account_level_replay"]
            self.assertEqual(1, account["account_trades"])
            self.assertEqual(1, account["skip_counts"]["ticker_position_open"])
            self.assertEqual("failed", account["skipped_decisions"][0]["candidate_id"])

if __name__ == "__main__":
    unittest.main()
