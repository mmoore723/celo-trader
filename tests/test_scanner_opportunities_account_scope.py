"""Account-isolation contract test for Scanner Opportunities."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from api.routes.signals import get_gate_scorecard, get_scanner_opportunities
from database.schema import _init_db_at


class ScannerOpportunitiesAccountScopeTests(unittest.TestCase):
    def test_existing_journal_database_is_upgraded_for_detailed_opportunities(self) -> None:
        """A pre-context signal history must migrate before the page reads it."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy-paper.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE signal_journal ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ticker TEXT NOT NULL, "
                "strategy_id TEXT NOT NULL, direction TEXT NOT NULL, confidence REAL NOT NULL, "
                "outcome TEXT NOT NULL, reason_code TEXT, reason_detail TEXT)"
            )
            conn.commit()
            conn.close()

            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(signal_journal)")}
            conn.close()

        self.assertTrue({"trade_id", "context_json", "tier", "broker_account_id"}.issubset(columns))

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

    def test_contract_selected_plan_includes_real_pricing_and_setup_facts(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate-1", "2026-08-13T10:02:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .84,
                 "main", "paper:new", "blocked", json.dumps({"or_high": 332.50, "or_low": 328.10, "vwap": 330.80})),
            )
            context = {
                "strategy_meta": {"shadow_candidate_id": "candidate-1"},
                "entry_plan": {"trigger": "Wait for the one-minute retouch to hold", "underlying_price": 333.12, "estimated_entry_price": 2.15},
                "contract": {"symbol": "TSLA260813C00332500", "strike": 332.5, "expiry": "2026-08-13", "bid": 2.00, "ask": 2.05},
                "contract_recipe": {"option_type": "CALL", "strike_rule": "closest out-of-the-money strike", "maximum_cost": 750.0},
                "planned_quantity": 2,
                "exit_plan": {"summary": "Exit at the executable bid after 90 minutes."},
            }
            conn.execute(
                "INSERT INTO signal_journal (ts, ticker, strategy_id, direction, confidence, outcome, reason_code, reason_detail, context_json, tier, broker_account_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:02:01-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .84, "blocked", "spread_too_wide", "spread 11% > 8% max", json.dumps(context), "main", "paper:new"),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                try:
                    yield conn
                    conn.commit()
                finally:
                    pass

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        entry = response["entries"][0]
        self.assertEqual("contract_selected", entry["plan_status"])
        self.assertEqual("call", entry["option_type"])
        self.assertEqual("TSLA260813C00332500", entry["contract"]["symbol"])
        self.assertEqual(2.15, entry["entry_plan"]["estimated_entry_price"])
        self.assertEqual(2, entry["planned_quantity"])
        self.assertEqual(332.50, entry["setup_details"]["or_high"])
        self.assertEqual("CALL", entry["contract_recipe"]["option_type"])
        self.assertEqual(750.0, entry["contract_recipe"]["maximum_cost"])

    def test_long_direction_without_a_trade_is_presented_as_a_call_plan(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate-long", "2026-08-13T10:03:00-04:00", "SPY", "V2_SPY_TREND_CONT", "long", .80,
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

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        self.assertEqual("call", response["entries"][0]["option_type"])
        self.assertEqual("CALL", response["entries"][0]["contract_recipe"]["option_type"])
        self.assertEqual("default_profile", response["entries"][0]["contract_recipe"]["recipe_source"])

    def test_decision_time_setup_facts_extend_the_original_candidate_plan(self) -> None:
        """The learner view must retain a recorded retouch level from entry evaluation."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate-context", "2026-08-13T10:04:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .85,
                 "main", "paper:new", "blocked", json.dumps({"or_high": 332.50, "or_low": 328.10})),
            )
            context = {"strategy_meta": {"shadow_candidate_id": "candidate-context", "retest_level": 332.50}}
            conn.execute(
                "INSERT INTO signal_journal (ts, ticker, strategy_id, direction, confidence, outcome, reason_code, reason_detail, context_json, tier, broker_account_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:04:01-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .85, "blocked",
                 "spread_too_wide", "spread too wide", json.dumps(context), "main", "paper:new"),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                try:
                    yield conn
                    conn.commit()
                finally:
                    pass

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        details = response["entries"][0]["setup_details"]
        self.assertEqual(332.50, details["or_high"])
        self.assertEqual(328.10, details["or_low"])
        self.assertEqual(332.50, details["retest_level"])

    def test_blocked_signal_keeps_a_display_only_contract_snapshot(self) -> None:
        """A learner can review the exact option screened before a gate stopped it."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate-preview", "2026-08-13T10:05:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .86,
                 "main", "paper:new", "blocked"),
            )
            context = {
                "strategy_meta": {"shadow_candidate_id": "candidate-preview"},
                "contract_preview": {
                    "status": "selected", "observed_at": "2026-08-13T10:05:01-04:00",
                    "underlying_price": 333.12, "symbol": "TSLA260821C00335000",
                    "strike": 335.0, "expiry": "2026-08-21", "bid": 2.10, "ask": 2.20,
                    "planned_entry_price": 2.31, "planned_contracts": 1,
                    "estimated_position_cost": 231.0,
                },
                "exit_plan": {"summary": "Hold the same selected contract for 90 minutes, then exit at the executable bid."},
            }
            conn.execute(
                "INSERT INTO signal_journal (ts, ticker, strategy_id, direction, confidence, outcome, reason_code, reason_detail, context_json, tier, broker_account_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:05:01-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .86, "blocked",
                 "ai_decision_veto", "conflicting trend context", json.dumps(context), "main", "paper:new"),
            )
            conn.execute(
                """INSERT INTO candidate_option_quote_observations
                   (candidate_id, observed_at, observation_kind, contract_symbol, bid, ask, mid, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("candidate-preview", "2026-08-13T10:05:01-04:00", "entry",
                 "TSLA260821C00335000", 2.10, 2.20, 2.15, "test"),
            )
            conn.execute(
                """INSERT INTO candidate_option_quote_observations
                   (candidate_id, observed_at, observation_kind, contract_symbol, bid, ask, mid, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("candidate-preview", "2026-08-13T10:35:01-04:00", "mark_30m",
                 "TSLA260821C00335000", 2.42, 2.50, 2.46, "test"),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                try:
                    yield conn
                    conn.commit()
                finally:
                    pass

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        preview = response["entries"][0]["contract_preview"]
        self.assertEqual("selected", preview["status"])
        self.assertEqual("TSLA260821C00335000", preview["symbol"])
        self.assertEqual(335.0, preview["strike"])
        self.assertEqual(2.31, preview["planned_entry_price"])
        self.assertEqual(1, preview["planned_contracts"])
        self.assertEqual("contract_preview", response["entries"][0]["plan_status"])
        timeline = response["entries"][0]["option_quote_timeline"]
        self.assertEqual(["entry", "mark_30m"], [mark["observation_kind"] for mark in timeline])
        self.assertEqual(10.0, timeline[1]["executable_return_pct"])

    def test_candidate_plan_survives_even_before_a_journal_outcome(self) -> None:
        """An early safety gate must not erase a plan a learner could inspect."""
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            metadata = {
                "or_high": 332.50,
                "manual_plan": {
                    "entry_plan": {"underlying_price": 333.12, "trigger": "first retouch"},
                    "contract_preview": {
                        "status": "selected", "symbol": "TSLA260821C00335000", "strike": 335.0,
                        "expiry": "2026-08-21", "bid": 2.10, "ask": 2.20,
                        "planned_entry_price": 2.31, "planned_contracts": 1,
                    },
                    "exit_plan": {"summary": "Exit after 90 minutes at the executable bid."},
                },
            }
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate-early", "2026-08-13T10:06:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .82,
                 "main", "paper:new", "pending", json.dumps(metadata)),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                try:
                    yield conn
                    conn.commit()
                finally:
                    pass

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        entry = response["entries"][0]
        self.assertEqual("TSLA260821C00335000", entry["contract_preview"]["symbol"])
        self.assertEqual(333.12, entry["entry_plan"]["underlying_price"])
        self.assertEqual("Exit after 90 minutes at the executable bid.", entry["exit_plan"]["summary"])

    def test_key_chart_levels_are_not_lost_when_metadata_has_many_technical_fields(self) -> None:
        from api.routes.signals import _setup_details

        details = _setup_details({
            **{f"diagnostic_{index}": index for index in range(30)},
            "or_high": 332.50,
            "or_low": 328.10,
            "retest_level": 332.50,
            "vwap": 330.80,
        })

        self.assertEqual(332.50, details["or_high"])
        self.assertEqual(328.10, details["or_low"])
        self.assertEqual(332.50, details["retest_level"])
        self.assertLessEqual(len(details), 16)

    def test_legacy_unlinked_veto_is_reconciled_without_double_counting(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("legacy-veto", "2026-08-13T10:23:09-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .78,
                 "main", "paper:new", "pending"),
            )
            conn.execute(
                "INSERT INTO signal_journal (ts, ticker, strategy_id, direction, confidence, outcome, reason_code, reason_detail, context_json, tier, broker_account_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:23:13-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .78,
                 "blocked", "ai_decision_veto", "1-hour trend opposed the bullish setup", "{}", "main", "paper:new"),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                yield conn

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ):
                response = get_scanner_opportunities(
                    date="2026-08-13", ticker=None, strategy=None, outcome=None, limit=500,
                )
            conn.close()

        self.assertEqual(1, response["summary"]["total"])
        self.assertEqual(1, response["summary"]["blocked"])
        self.assertEqual(1, response["summary"]["routed"])
        self.assertEqual(0, response["summary"]["unresolved"])
        self.assertEqual("ai_decision_veto", response["entries"][0]["reason_code"])
        self.assertIn("1-hour trend", response["entries"][0]["reason_detail"])

    def test_gate_scorecard_prefers_executable_option_outcome(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, gate_reason, direction_correct, outcome_observed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ai-veto", "2026-08-13T10:00:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .78,
                 "main", "paper:new", "blocked", "ai_decision_veto", 1, "2026-08-13T11:00:00-04:00"),
            )
            conn.execute(
                "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, direction_correct, outcome_observed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ai-approved", "2026-08-13T10:20:00-04:00", "TSLA", "V2_ORB_PULLBACK", "bullish", .81,
                 "main", "paper:new", "entered", 1, "2026-08-13T11:20:00-04:00"),
            )
            conn.execute(
                "INSERT INTO ai_reasoning_log (ts, event_type, ticker, feature_snapshot_json, prompt, response_text, model, applied) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:20:02-04:00", "entry_veto", "TSLA",
                 json.dumps({"candidate_id": "ai-approved", "strategy_id": "V2_ORB_PULLBACK", "direction": "bullish", "decision_action": "approve"}),
                 "test", "ACTION: approve | SIZE: 1.0 | REASON: aligned", "test", 0),
            )
            for kind, observed_at, bid, ask in (
                ("entry", "2026-08-13T10:00:01-04:00", 1.90, 2.00),
                ("mark_60m", "2026-08-13T11:00:01-04:00", 1.50, 1.60),
            ):
                conn.execute(
                    "INSERT INTO candidate_option_quote_observations (candidate_id, observed_at, observation_kind, contract_symbol, bid, ask, mid, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("ai-veto", observed_at, kind, "TSLA260821C00350000", bid, ask, (bid + ask) / 2, "test"),
                )
            conn.commit()

            @contextmanager
            def test_conn():
                yield conn

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ), patch("database._now_et", return_value=datetime.fromisoformat("2026-08-14T12:00:00-04:00")):
                response = get_gate_scorecard(days=30)
            conn.close()

        row = response["rows"][0]
        self.assertEqual(1, row["measured"])
        self.assertEqual(1, row["option_measured"])
        self.assertEqual(1, row["avoided_losers"])
        self.assertEqual(0, row["rejected_winners"])
        self.assertEqual(-25.0, row["avg_rejected_option_return_pct"])
        self.assertEqual(1, row["allowed"]["decisions"])
        self.assertEqual(1, row["allowed"]["measured"])
        self.assertEqual(100.0, row["allowed"]["win_rate_pct"])
        self.assertEqual(2, row["independent_episodes"])
        self.assertFalse(row["enforced"])

    def test_gate_scorecard_treats_repeated_minutes_as_one_delayed_episode(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "paper.db"
            _init_db_at(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            for candidate_id, observed_at, gate_reason in (
                ("first-veto", "2026-08-13T10:00:00-04:00", "ai_decision_veto"),
                ("later-approve", "2026-08-13T10:05:00-04:00", None),
            ):
                conn.execute(
                    "INSERT INTO shadow_candidates (candidate_id, observed_at, ticker, strategy_id, direction, confidence, tier, broker_account_id, final_outcome, gate_reason, direction_correct, outcome_observed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (candidate_id, observed_at, "TSLA", "V2_ORB_PULLBACK", "bullish", .78,
                     "main", "paper:new", "pending", gate_reason, 1, "2026-08-13T11:05:00-04:00"),
                )
            conn.execute(
                "INSERT INTO ai_reasoning_log (ts, event_type, ticker, feature_snapshot_json, prompt, response_text, model, applied) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-08-13T10:05:02-04:00", "entry_veto", "TSLA",
                 json.dumps({"candidate_id": "later-approve", "strategy_id": "V2_ORB_PULLBACK", "direction": "bullish", "decision_action": "approve"}),
                 "test", "ACTION: approve | SIZE: 1.0 | REASON: aligned", "test", 0),
            )
            conn.commit()

            @contextmanager
            def test_conn():
                yield conn

            with patch("database.get_conn", test_conn), patch(
                "config.get_settings", return_value={"active_broker_account_id": "paper:new"},
            ), patch("database._now_et", return_value=datetime.fromisoformat("2026-08-14T12:00:00-04:00")):
                response = get_gate_scorecard(days=30)
            conn.close()

        row = response["rows"][0]
        self.assertEqual(2, row["raw_decisions"])
        self.assertEqual(1, row["independent_episodes"])
        self.assertEqual(1, row["vetoes"])
        self.assertEqual(1, row["delayed_then_allowed"])
        self.assertEqual(0, row["allowed"]["decisions"])
