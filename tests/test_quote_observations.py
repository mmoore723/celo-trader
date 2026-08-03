"""Contract tests for paper-only option quote evidence capture."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from database.option_quotes import record_paper_option_quote
from database.schema import _init_db_at


class PaperOptionQuoteTests(unittest.TestCase):
    def test_mark_is_deduped_per_minute_but_entry_and_exit_are_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """INSERT INTO trades
                   (ticker, contract_symbol, option_type, strike, expiry, contracts,
                    entry_price, entry_time, entry_reason, status, paper, tier)
                   VALUES ('TSLA', 'TSLA260807C00300000', 'call', 300, '2026-08-07',
                           1, 5, '2026-08-03T10:00:00', 'test', 'open', 1, 'main')"""
            )
            conn.commit()

            with patch("database.option_quotes.get_conn", return_value=conn):
                common = dict(
                    trade_id=1, contract_symbol="TSLA260807C00300000",
                    observed_at=datetime(2026, 8, 3, 10, 0, 5),
                    quote={"bid": 4.9, "ask": 5.1}, source="test",
                )
                self.assertTrue(record_paper_option_quote(observation_kind="entry", fill_price=5.1, **common))
                self.assertTrue(record_paper_option_quote(observation_kind="mark", **common))
                self.assertTrue(record_paper_option_quote(observation_kind="mark", **common))
                self.assertTrue(record_paper_option_quote(observation_kind="exit", fill_price=4.8, **common))

            rows = conn.execute(
                "SELECT observation_kind, bid, ask, mid, fill_price "
                "FROM option_quote_observations ORDER BY id"
            ).fetchall()
            conn.close()

        self.assertEqual(["entry", "mark", "exit"], [row[0] for row in rows])
        self.assertEqual(("entry", 4.9, 5.1, 5.0, 5.1), rows[0])
        self.assertEqual(("exit", 4.9, 5.1, 5.0, 4.8), rows[-1])

    def test_invalid_kind_is_rejected_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            record_paper_option_quote(
                trade_id=1, contract_symbol="TSLA260807C00300000",
                observation_kind="unknown", observed_at=datetime(2026, 8, 3, 10),
                quote=None, source="test",
            )
