from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.jobs.reconcile_tradier_alpaca_candidate_fills import build_report


class TradierAlpacaCandidateReconciliationTests(unittest.TestCase):
    def _database(self, directory: str) -> Path:
        path = Path(directory) / "fills.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY, ticker TEXT, contract_symbol TEXT, contracts INTEGER,
                entry_price REAL, exit_price REAL, realized_pnl REAL, entry_time TEXT,
                exit_time TEXT, strategy_id TEXT, candidate_id TEXT, status TEXT
            );
            CREATE TABLE shadow_candidates (
                candidate_id TEXT PRIMARY KEY, ticker TEXT, strategy_id TEXT,
                linked_trade_id INTEGER
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, contract_symbol TEXT,
                bid REAL, ask REAL, source TEXT
            );
        """)
        conn.close()
        return path

    def test_exact_contract_reconciles_entry_and_exit_cross_feed_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._database(tmp)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (1, "SPY", "SPY-C", 1, 1.10, 1.10, 0.0,
                 "2026-08-01T10:00:00-04:00", "2026-08-01T10:30:00-04:00",
                 "V2_SPY_TREND_CONT", "candidate", "closed"),
            )
            conn.execute(
                "INSERT INTO shadow_candidates VALUES (?,?,?,?)",
                ("candidate", "SPY", "V2_SPY_TREND_CONT", 1),
            )
            conn.executemany(
                "INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?)", [
                    ("candidate", "entry", "SPY-C", .99, 1.00, "tradier_preview"),
                    ("candidate", "mark_30m", "SPY-C", 2.00, 2.01, "tradier_followup"),
                ],
            )
            conn.commit()
            conn.close()

            report = build_report(path, first_trade_id=1, last_trade_id=1)
            self.assertEqual(1, report["matched_trades"])
            row = report["matched_trade_details"][0]
            self.assertEqual(100.0, row["tradier_reference_pnl"])
            self.assertEqual(10.0, row["entry_cross_feed_adverse_dollars"])
            self.assertEqual(90.0, row["exit_cross_feed_adverse_dollars"])
            self.assertEqual(100.0, row["total_cross_feed_adverse_dollars"])
            self.assertTrue(report["validation"]["actual_pnl_reconciles"]["passed"])
            self.assertTrue(report["validation"]["cross_feed_gap_reconciles"]["passed"])

    def test_contract_mismatch_is_excluded_instead_of_simulated(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._database(tmp)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (2, "TSLA", "TSLA-C-350", 1, 5.0, 6.0, 100.0,
                 "2026-08-01T10:00:00-04:00", "2026-08-01T11:30:00-04:00",
                 "V2_TSLA_TWO_LEG_TREND_PULLBACK", "candidate", "closed"),
            )
            conn.execute(
                "INSERT INTO shadow_candidates VALUES (?,?,?,?)",
                ("candidate", "TSLA", "V2_TSLA_TWO_LEG_TREND_PULLBACK", 2),
            )
            conn.executemany(
                "INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?)", [
                    ("candidate", "entry", "TSLA-C-355", 4.9, 5.0, "tradier_preview"),
                    ("candidate", "mark_90m", "TSLA-C-355", 6.0, 6.1, "tradier_followup"),
                ],
            )
            conn.commit()
            conn.close()

            report = build_report(path, first_trade_id=2, last_trade_id=2)
            self.assertEqual(0, report["matched_trades"])
            self.assertEqual(1, report["excluded_reason_counts"]["candidate_entry_contract_mismatch"])


if __name__ == "__main__":
    unittest.main()
