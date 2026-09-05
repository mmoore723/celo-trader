from __future__ import annotations

import json
import importlib.util
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from config.atomic_files import atomic_update_json
from database.schema import _init_db_at
from database.trades import audit_trade_lineage, close_trade, insert_trade
from signal_journal.write import log_signal_outcome
from trading.entry.tick import _confirmed_entry_price, _entry_order_wait_seconds


class AtomicRuntimeStateTests(unittest.TestCase):
    def test_concurrent_updates_do_not_drop_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot_state.json"
            workers = [
                threading.Thread(
                    target=atomic_update_json,
                    args=(path, lambda state, i=i: {**state, f"field_{i}": i}),
                )
                for i in range(20)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            payload = json.loads(path.read_text())
            self.assertEqual({f"field_{i}" for i in range(20)}, set(payload))

    def test_update_repairs_a_truncated_legacy_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot_state.json"
            path.write_text('{"running":')
            atomic_update_json(path, lambda state: {**state, "running": False})
            self.assertEqual({"running": False}, json.loads(path.read_text()))


class LoopLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        from trading.state.locks import _USER_STOP_EVENTS, _USER_THREADS

        _USER_STOP_EVENTS.clear()
        _USER_THREADS.clear()

    def test_graceful_shutdown_stops_registered_workers(self) -> None:
        from trading.state import (
            _get_stop_event,
            register_loop_thread,
            request_graceful_shutdown,
        )

        stopped = threading.Event()

        def worker() -> None:
            _get_stop_event("alice").wait(timeout=2)
            stopped.set()

        thread = threading.Thread(target=worker, daemon=True)
        register_loop_thread("alice", thread)
        thread.start()

        self.assertEqual([], request_graceful_shutdown(timeout=1))
        self.assertTrue(stopped.is_set())

    def test_collection_only_maintenance_allows_restart_resume(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "celo_lifespan_under_test",
            Path(__file__).parents[1] / "api" / "main" / "lifespan.py",
        )
        assert spec and spec.loader
        lifespan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lifespan)

        started: list[dict] = []

        class ImmediateThread:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def start(self):
                started.append(self.kwargs)

        auth_users = types.ModuleType("auth.users")
        auth_users.list_users = lambda: [{"user_id": "alice"}]
        trading_loop = types.ModuleType("trading.loop")
        trading_loop.run_trading_loop = lambda **kwargs: None

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "bot_state.json"
            state_path.write_text('{"running": true, "auto_start_disabled": false}')
            with patch.dict(sys.modules, {
                "auth.users": auth_users,
                "trading.loop": trading_loop,
            }), patch(
                "config.get_maintenance_state",
                return_value={"maintenance_mode": True, "collection_only": True},
            ), patch(
                "config.get_api_keys",
                return_value={
                    "alpaca_api_key": "alpaca-key",
                    "alpaca_secret_key": "alpaca-secret",
                    "tradier_api_key": "tradier-key",
                    "tradier_market_api_key": "tradier-live-market-key",
                    "tradier_account_id": "tradier-account",
                },
            ), patch("config.get_bot_state_path", return_value=state_path), patch.object(
                lifespan.threading, "Thread", ImmediateThread,
            ), patch("database.log_event"):
                lifespan._auto_start_bot_if_needed()

        self.assertEqual(1, len(started))
        self.assertEqual({"user_id": "alice"}, started[0]["kwargs"])

    def test_restart_does_not_resume_or_show_money_without_broker_credentials(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "celo_lifespan_missing_credentials",
            Path(__file__).parents[1] / "api" / "main" / "lifespan.py",
        )
        assert spec and spec.loader
        lifespan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lifespan)

        started: list[dict] = []

        class ImmediateThread:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def start(self):
                started.append(self.kwargs)

        auth_users = types.ModuleType("auth.users")
        auth_users.list_users = lambda: [{"user_id": "guest"}]
        trading_loop = types.ModuleType("trading.loop")
        trading_loop.run_trading_loop = lambda **kwargs: None

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "bot_state.json"
            state_path.write_text(json.dumps({
                "running": True,
                "account_balance": 5000.0,
                "day_start_balance": 5000.0,
            }))
            with patch.dict(sys.modules, {
                "auth.users": auth_users,
                "trading.loop": trading_loop,
            }), patch(
                "config.get_maintenance_state",
                return_value={"maintenance_mode": False, "collection_only": False},
            ), patch(
                "config.get_api_keys",
                return_value={
                    "alpaca_api_key": "", "alpaca_secret_key": "",
                    "tradier_api_key": "", "tradier_market_api_key": "",
                    "tradier_account_id": "", "tradier_live_account_id": "",
                },
            ), patch("config.get_bot_state_path", return_value=state_path), patch.object(
                lifespan.threading, "Thread", ImmediateThread,
            ):
                lifespan._auto_start_bot_if_needed()

            state = json.loads(state_path.read_text())

        self.assertEqual([], started)
        self.assertFalse(state["running"])
        self.assertEqual("stopped", state["mode"])
        self.assertEqual(0.0, state["account_balance"])
        self.assertEqual(0.0, state["day_start_balance"])


class DurableTradeLineageTests(unittest.TestCase):
    def test_reviewed_strategy_context_survives_direct_trade_insert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades_paper.db"
            _init_db_at(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            now = datetime.fromisoformat("2026-08-14T10:31:00-04:00")
            strategy_context = json.dumps({
                "strategy_id": "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
                "previous_high": 351.25,
                "direction": "bullish",
            }, sort_keys=True)

            with patch("database.trades.get_conn", return_value=conn):
                trade_id = insert_trade(
                    "TSLA", "TSLA260821C00350000", "call", 350, "2026-08-21",
                    1, 2.05, now, "vwap displacement",
                    strategy_id="CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
                    strategy_context_json=strategy_context,
                )

            row = conn.execute(
                "SELECT strategy_context_json FROM trades WHERE id = ?", (trade_id,),
            ).fetchone()
            conn.close()

        self.assertEqual(json.loads(strategy_context), json.loads(row["strategy_context_json"]))

    def test_broker_utc_fill_times_are_stored_as_eastern_wall_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades_paper.db"
            _init_db_at(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            entry = datetime.fromisoformat("2026-08-14T10:01:00-04:00")
            with patch("database.trades.get_conn", return_value=conn):
                trade_id = insert_trade(
                    "SPY", "SPY260821C00650000", "call", 650, "2026-08-21",
                    1, 1.25, entry, "test", entry_fill_time="2026-08-14T14:01:02Z",
                )
                with patch("database.trades._upsert_daily_summary"), patch(
                    "config.get_settings", return_value={"last_known_balance": 5000.0},
                ), patch("config.save_settings"), patch(
                    "database.option_quotes.record_paper_option_quote", return_value=True,
                ):
                    close_trade(
                        trade_id, 1.30, entry, "test", confirmed_fill_price=1.30,
                        exit_fill_time="2026-08-14T14:31:03Z",
                    )
            row = conn.execute(
                "SELECT entry_fill_time, exit_fill_time FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            conn.close()

        self.assertEqual("2026-08-14T10:01:02", row["entry_fill_time"])
        self.assertEqual("2026-08-14T10:31:03", row["exit_fill_time"])

    def test_entry_patience_does_not_starve_open_position_exits(self) -> None:
        self.assertEqual(45, _entry_order_wait_seconds(has_open_positions=False))
        self.assertEqual(10, _entry_order_wait_seconds(has_open_positions=True))

    def test_entry_accounting_prefers_native_broker_average_fill(self) -> None:
        self.assertEqual(
            1.87,
            _confirmed_entry_price({"filled_avg_price": "1.87"}, 1.95),
        )
        self.assertEqual(
            1.84,
            _confirmed_entry_price({
                "confirmed_fill_price": 1.84,
                "filled_avg_price": "1.87",
            }, 1.95),
        )

    def test_signal_order_fill_and_exit_are_durably_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades_paper.db"
            _init_db_at(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            candidate_id = "candidate-1"
            conn.execute(
                """INSERT INTO shadow_candidates
                   (candidate_id, observed_at, ticker, strategy_id, direction,
                    confidence, tier, final_outcome)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (candidate_id, "2026-08-14T10:00:00-04:00", "TSLA",
                 "V2_ORB_PULLBACK", "bullish", .82, "main"),
            )
            conn.commit()
            now = datetime.fromisoformat("2026-08-14T10:01:00-04:00")
            context = {"strategy_meta": {"shadow_candidate_id": candidate_id}}

            with patch("database.trades.get_conn", return_value=conn):
                trade_id = insert_trade(
                    "TSLA", "TSLA260821C00350000", "call", 350, "2026-08-21",
                    1, 2.10, now, "reviewed signal", strategy_id="V2_ORB_PULLBACK",
                    candidate_id=candidate_id, entry_order_id="entry-order-1",
                    entry_fill_time=now,
                )

            with patch("signal_journal.write.get_conn", return_value=conn), patch(
                "shadow_ledger.get_conn", return_value=conn,
            ), patch("signal_journal.write._now_et", return_value=now):
                journal_id = log_signal_outcome(
                    "TSLA", "V2_ORB_PULLBACK", "bullish", .82, "entered",
                    trade_id=trade_id, context=context,
                )
            self.assertIsNotNone(journal_id)

            with patch("database.trades.get_conn", return_value=conn):
                self.assertEqual([], audit_trade_lineage(trade_id))
                with patch("database.trades._upsert_daily_summary"), patch(
                    "config.get_settings", return_value={"last_known_balance": 5000.0},
                ), patch("config.save_settings"):
                    close_trade(
                        trade_id, 2.40, now, "test_exit", confirmed_fill_price=2.40,
                        peak_price=2.55, mae_price=2.00, paper=False,
                        exit_order_id="exit-order-1", exit_fill_time=now,
                    )
                self.assertEqual([], audit_trade_lineage(trade_id))

            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            candidate = conn.execute(
                "SELECT linked_trade_id, final_outcome FROM shadow_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            conn.close()

            self.assertEqual(candidate_id, row["candidate_id"])
            self.assertEqual("entry-order-1", row["entry_order_id"])
            self.assertEqual("exit-order-1", row["exit_order_id"])
            self.assertEqual(trade_id, candidate["linked_trade_id"])
            self.assertEqual("entered", candidate["final_outcome"])

    def test_realized_pnl_uses_broker_fill_not_requested_exit_limit(self) -> None:
        """A worse broker fill must be visible in both exit price and P&L."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades_paper.db"
            _init_db_at(path)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            now = datetime.fromisoformat("2026-08-21T10:01:00-04:00")

            with patch("database.trades.get_conn", return_value=conn):
                trade_id = insert_trade(
                    "SPY", "SPY260828P00760000", "put", 760, "2026-08-28",
                    2, 2.00, now, "reviewed signal",
                    strategy_id="V2_SPY_TREND_CONT",
                )
                with patch("database.trades._upsert_daily_summary"), patch(
                    "config.get_settings", return_value={"last_known_balance": 5000.0},
                ), patch("config.save_settings"):
                    pnl = close_trade(
                        trade_id,
                        exit_price=2.40,
                        exit_time=now,
                        exit_reason="test_exit",
                        confirmed_fill_price=2.20,
                        paper=False,
                    )

            row = conn.execute(
                "SELECT exit_price, realized_pnl FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            conn.close()

            self.assertAlmostEqual(2.20, row["exit_price"])
            # Gross gain is $40; live round-trip commissions are $2.60.
            self.assertAlmostEqual(37.40, pnl)
            self.assertAlmostEqual(37.40, row["realized_pnl"])


if __name__ == "__main__":
    unittest.main()
