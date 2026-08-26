from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from database.schema import _init_db_at
from database.underlying_quotes import record_underlying_quote


class UnderlyingQuoteTests(unittest.TestCase):
    def test_records_account_scoped_bid_ask_evidence(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            _init_db_at(path)

            @contextmanager
            def temp_conn():
                conn = sqlite3.connect(path)
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()

            with patch("database.underlying_quotes.get_conn", temp_conn):
                saved = record_underlying_quote(
                    "amzn", {"bp": 230.10, "ap": 230.14}, broker_account_id="mine",
                    observed_at=datetime.fromisoformat("2026-08-26T10:00:00-04:00"),
                )
            with sqlite3.connect(path) as conn:
                row = conn.execute(
                    "SELECT broker_account_id,ticker,bid,ask,mid FROM underlying_quote_observations"
                ).fetchone()
            self.assertTrue(saved)
            self.assertEqual(("mine", "AMZN", 230.10, 230.14, 230.12), row)


if __name__ == "__main__":
    unittest.main()
