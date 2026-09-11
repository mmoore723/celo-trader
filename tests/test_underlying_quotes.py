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
    def test_additive_migration_preserves_old_rows_and_is_repeatable(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE underlying_quote_observations (id INTEGER PRIMARY KEY,broker_account_id TEXT,ticker TEXT,observed_at TEXT,bid REAL,ask REAL,mid REAL,source TEXT)')
                conn.execute("INSERT INTO underlying_quote_observations VALUES (1,'a','META','2026-09-10T10:00:00',100,101,100.5,'alpaca')")
            _init_db_at(path);_init_db_at(path)
            with sqlite3.connect(path) as conn:
                self.assertEqual((1,'a','META','2026-09-10T10:00:00',100,101,100.5,'alpaca',None),conn.execute('SELECT * FROM underlying_quote_observations').fetchone())

    def test_quote_time_stays_distinct_from_receipt_time(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.db';_init_db_at(path)
            @contextmanager
            def connect():
                with sqlite3.connect(path) as conn:
                    yield conn
            with patch('database.underlying_quotes.get_conn',connect):
                for ticker,stamp in [('META','2026-09-10T13:59:50Z'),('SPY',None),('TSLA','bad')]:
                    record_underlying_quote(ticker,{'ap':101,'bp':100,'t':stamp},observed_at=datetime.fromisoformat('2026-09-10T10:00:00-04:00'))
            with sqlite3.connect(path) as conn:
                rows=conn.execute('SELECT ticker,observed_at,quote_at FROM underlying_quote_observations ORDER BY ticker').fetchall()
            self.assertEqual(('META','2026-09-10T10:00:00','2026-09-10T13:59:50+00:00'),rows[0])
            self.assertIsNone(rows[1][2]);self.assertIsNone(rows[2][2])

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
