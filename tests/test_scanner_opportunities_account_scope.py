"""Account-isolation contract test for Scanner Opportunities."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from api.routes.signals import get_scanner_opportunities
from database.schema import _init_db_at


class ScannerOpportunitiesAccountScopeTests(unittest.TestCase):
    def test_active_account_cannot_see_another_accounts_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            columns = (
                "candidate_id, observed_at, ticker, strategy_id, direction, confidence, "
                "tier, broker_account_id, final_outcome"
            )
            conn.execute(
                f"INSERT INTO shadow_candidates ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("old", "2026-08-13T10:00:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .8,
                 "main", "paper:old", "blocked"),
            )
            conn.execute(
                f"INSERT INTO shadow_candidates ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("new", "2026-08-13T10:01:00-04:00", "SPY", "V2_SPY_TREND_CONT", "bearish", .81,
                 "main", "paper:new", "blocked"),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                try:
                    yield conn
                    conn.commit()
                finally:
                    pass

            # The endpoint deliberately imports the active database connection
            # inside the request handler, so patch that public dependency—not
            # a module-level alias that does not exist.
            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                # A direct Python call bypasses FastAPI's normal Query()
                # injection, so provide the endpoint's ordinary limit value.
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        self.assertTrue(response["account_scoped"])
        self.assertEqual(1, response["summary"]["total"])
        self.assertEqual("SPY", response["entries"][0]["ticker"])
