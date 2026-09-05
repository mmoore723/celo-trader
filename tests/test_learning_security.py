import unittest
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ai_reasoning.learning_ranker import MIN_EPISODES, train_shadow_model
from api.routes.learning import PracticeAnswer, _practice_public_payload, _sync_curated_examples, answer_practice
from auth.context import set_current_user
from fastapi import HTTPException


class LearningSecurityTests(unittest.TestCase):
    def example(self):
        return {
            "example_id": "ex-1", "strategy_id": "V2_SPY_TREND_CONT",
            "strategy_version": "2.1.0", "ticker": "SPY",
            "observed_at": "2026-08-21T10:10:00-04:00", "decision_bar_index": 1,
            "bars": [{"time": "10:09"}, {"time": "10:10"}, {"time": "10:11"}],
            "category": "clean_win", "outcome": "entered", "direction": "bullish",
            "direction_correct": 1, "directional_move_pct": 0.3,
            "coach": {"summary": "future summary", "prompt": "future prompt"},
            "gate_reason": None, "gate_detail": None,
        }

    def test_pre_answer_payload_contains_no_future_or_label_fields(self):
        payload = _practice_public_payload(self.example())
        self.assertEqual(2, len(payload["bars"]))
        forbidden = {"category", "outcome", "direction", "direction_correct",
                     "directional_move_pct", "coach", "gate_reason", "gate_detail"}
        self.assertTrue(forbidden.isdisjoint(payload))

    def test_ranker_cannot_train_below_honest_threshold(self):
        result = train_shadow_model([self.example()] * 20)
        self.assertEqual("collecting", result["status"])
        self.assertEqual(MIN_EPISODES, result["required"])
        self.assertFalse(result["order_authority"])

    def test_practice_session_is_owned_by_authenticated_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learning.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE learning_examples(example_id TEXT PRIMARY KEY,evidence_json TEXT);
                CREATE TABLE learning_practice_sessions(
                  session_id TEXT PRIMARY KEY,user_id TEXT,example_id TEXT,expected_answer TEXT,
                  created_at TEXT,expires_at TEXT,answered_at TEXT,answer TEXT,correct INTEGER);
            """)
            now = datetime.now().astimezone()
            conn.execute("INSERT INTO learning_examples VALUES (?,?)", ("ex-1", json.dumps(self.example())))
            conn.execute("INSERT INTO learning_practice_sessions VALUES (?,?,?,?,?,?,?,?,?)",
                         ("secret", "alice", "ex-1", '[\"call\"]', now.isoformat(),
                          (now + timedelta(minutes=10)).isoformat(), None, None, None))
            conn.commit(); conn.close()

            @contextmanager
            def test_conn():
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row
                try:
                    yield db; db.commit()
                finally:
                    db.close()

            with patch("database.get_conn", test_conn):
                try:
                    set_current_user("bob", "bob", False)
                    with self.assertRaises(HTTPException) as raised:
                        answer_practice("secret", PracticeAnswer(answer="call"))
                    self.assertEqual(404, raised.exception.status_code)
                    set_current_user("alice", "alice", False)
                    result = answer_practice("secret", PracticeAnswer(answer="call"))
                    self.assertTrue(result["correct"])
                finally:
                    set_current_user("system", "system", False)

    def test_curator_persists_only_real_chart_complete_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learning.db"
            from database.schema import _init_db_at
            _init_db_at(path)

            @contextmanager
            def test_conn():
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row
                try:
                    yield db; db.commit()
                finally:
                    db.close()

            row = {"candidate_id": "real-1", "observed_at": "2026-08-21T10:10:00-04:00",
                   "strategy_id": "V2_SPY_TREND_CONT", "ticker": "SPY", "direction": "bullish",
                   "confidence": 0.8, "metadata_json": '{"strategy_version":"2.1.0"}',
                   "final_outcome": "observed_only", "direction_correct": 1,
                   "outcome_observed_at": "2026-08-21T11:10:00-04:00"}
            with test_conn() as conn:
                conn.execute("""INSERT INTO shadow_candidates
                    (candidate_id,observed_at,ticker,strategy_id,direction,confidence,tier,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?)""", (row["candidate_id"], row["observed_at"], row["ticker"],
                    row["strategy_id"], row["direction"], row["confidence"], "main", row["metadata_json"]))
            bars = [{"time": f"2026-08-21T10:{minute:02d}:00", "open": 1, "high": 2,
                     "low": 1, "close": 2, "volume": 100} for minute in range(20)]
            with patch("database.get_conn", test_conn), patch("api.routes.learning._candidate_rows", return_value=[row]), \
                 patch("api.routes.learning._chart_evidence", return_value=(bars, 9)):
                self.assertEqual(1, _sync_curated_examples())
            with test_conn() as conn:
                saved = conn.execute("SELECT candidate_id,published FROM learning_examples").fetchone()
            self.assertEqual(("real-1", 1), tuple(saved))


if __name__ == "__main__":
    unittest.main()
