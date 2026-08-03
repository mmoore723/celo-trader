"""Contract tests for paper-only option quote evidence capture."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from database.option_quotes import record_paper_option_quote
from database.schema import _init_db_at
from database.trades_query import get_all_trades
from shadow_ledger import record_router_candidate, resolve_candidate_from_context


class PaperOptionQuoteTests(unittest.TestCase):
    def test_existing_trade_table_migrates_before_account_index(self) -> None:
        """Older databases lack broker_account_id; init must add it before indexing."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, entry_time TEXT)"
            )
            conn.commit()
            conn.close()
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(trades)")}
            conn.close()

        self.assertIn("broker_account_id", columns)
        self.assertIn("idx_trades_broker_account", indexes)

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

    def test_trade_query_does_not_mix_broker_accounts(self) -> None:
        """A newly connected broker account must not inherit local P&L history."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            common = (
                "ticker, contract_symbol, option_type, strike, expiry, contracts, "
                "entry_price, entry_time, entry_reason, status, paper, tier, broker_account_id"
            )
            conn.execute(
                f"INSERT INTO trades ({common}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", "TSLA260807C00300000", "call", 300, "2026-08-07", 1,
                 5, "2026-08-03T10:00:00", "old", "closed", 1, "main", "alpaca:paper:old"),
            )
            conn.execute(
                f"INSERT INTO trades ({common}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", "TSLA260807P00300000", "put", 300, "2026-08-07", 1,
                 4, "2026-08-03T10:05:00", "new", "closed", 1, "main", "alpaca:paper:new"),
            )
            conn.commit()
            with patch("database.trades_query._conn_for_mode", return_value=conn):
                rows = get_all_trades(mode="paper", broker_account_id="alpaca:paper:new")
            conn.close()

        self.assertEqual(1, len(rows))
        self.assertEqual("new", rows[0]["entry_reason"])

    def test_shadow_candidate_links_router_signal_to_gate_outcome(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            signal = SimpleNamespace(
                strategy_id="INST_ORB", direction="bullish", confidence=0.81,
                trigger_bar="2026-08-03T10:00:00", tier="main", meta={"rvol": 1.8},
            )
            with patch("shadow_ledger.get_conn", return_value=conn):
                record_router_candidate("TSLA", signal)
                resolve_candidate_from_context(
                    {"strategy_meta": signal.meta}, "blocked", "budget", "cap reached", None,
                )
            row = conn.execute(
                "SELECT strategy_id, final_outcome, gate_reason, gate_detail "
                "FROM shadow_candidates"
            ).fetchone()
            conn.close()

        self.assertEqual(("INST_ORB", "blocked", "budget", "cap reached"), row)

    def test_shadow_candidate_records_same_session_directional_outcome(self) -> None:
        from shadow_ledger import resolve_due_directional_outcomes

        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            signal = SimpleNamespace(
                strategy_id="INST_ORB", direction="bullish", confidence=0.81,
                trigger_bar="2026-08-03T10:00:00", tier="main", meta={},
            )
            observed = datetime(2026, 8, 3, 10, 0)
            due = datetime(2026, 8, 3, 11, 1)
            with patch("shadow_ledger.get_conn", return_value=conn), patch(
                "shadow_ledger._now_et", side_effect=[observed, due],
            ):
                record_router_candidate("TSLA", signal, 300.0)
                resolve_due_directional_outcomes("TSLA", 303.0)
            row = conn.execute(
                "SELECT underlying_entry_price, underlying_exit_price, directional_move_pct, direction_correct "
                "FROM shadow_candidates"
            ).fetchone()
            conn.close()

        self.assertEqual((300.0, 303.0, 1.0, 1), tuple(row))
