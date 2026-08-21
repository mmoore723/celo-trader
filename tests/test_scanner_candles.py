"""Tests for durable, idempotent scanner-wide candle capture."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

from database.scanner_candles import record_scanner_candles
from database.schema import _init_db_at


class ScannerCandleTests(unittest.TestCase):
    def test_recording_is_idempotent_and_account_scoped(self) -> None:
        frame = pd.DataFrame({
            "time": [pd.Timestamp("2026-08-21 09:30"), pd.Timestamp("2026-08-21 09:31")],
            "open": [100, 101], "high": [102, 103], "low": [99, 100],
            "close": [101, 102], "volume": [1000, 1200],
        })
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            _init_db_at(path)

            from contextlib import contextmanager
            @contextmanager
            def temp_conn():
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()

            with patch("database.scanner_candles.get_conn", temp_conn):
                record_scanner_candles("aapl", frame, broker_account_id="one")
                record_scanner_candles("aapl", frame, broker_account_id="one")
                record_scanner_candles("aapl", frame, broker_account_id="two")

            with sqlite3.connect(path) as conn:
                rows = conn.execute(
                    "SELECT broker_account_id, ticker, COUNT(*) FROM scanner_candle_observations GROUP BY 1,2 ORDER BY 1"
                ).fetchall()
            self.assertEqual([("one", "AAPL", 2), ("two", "AAPL", 2)], rows)


if __name__ == "__main__":
    unittest.main()
