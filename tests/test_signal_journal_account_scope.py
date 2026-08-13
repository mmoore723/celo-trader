"""Regression tests for account-scoped scanner/signal history."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from database.schema import _init_db_at
from signal_journal.queries import get_todays_rows
from signal_journal.write import log_signal_outcome


class SignalJournalAccountScopeTests(unittest.TestCase):
    def test_reader_only_returns_active_account_signals(self) -> None:
        """A changed API key must not inherit another account's signal history."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            now = datetime(2026, 8, 13, 10, 0)

            with patch("signal_journal.write.get_conn", return_value=conn), patch(
                "signal_journal.write._now_et", return_value=now,
            ), patch("config.get_settings", return_value={"active_broker_account_id": "paper:old"}):
                self.assertIsNotNone(log_signal_outcome(
                    "TSLA", "V2_ORB_PULLBACK", "bullish", .8, "blocked", "budget", "old account",
                ))

            with patch("signal_journal.write.get_conn", return_value=conn), patch(
                "signal_journal.write._now_et", return_value=now,
            ), patch("config.get_settings", return_value={"active_broker_account_id": "paper:new"}):
                self.assertIsNotNone(log_signal_outcome(
                    "SPY", "V2_SPY_TREND_CONT", "bearish", .81, "blocked", "budget", "new account",
                ))

            with patch("signal_journal.queries.get_conn", return_value=conn), patch(
                "signal_journal.queries._now_et", return_value=now,
            ), patch("config.get_settings", return_value={"active_broker_account_id": "paper:new"}):
                rows = get_todays_rows()
            conn.close()

        self.assertEqual(1, len(rows))
        self.assertEqual("SPY", rows[0]["ticker"])
        self.assertEqual("paper:new", rows[0]["broker_account_id"])

