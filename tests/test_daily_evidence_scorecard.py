from __future__ import annotations

import sqlite3
import unittest

from database.schema import (
    _CREATE_BROKER_ORDER_EVENTS, _CREATE_CANDIDATE_OPTION_QUOTE_OBSERVATIONS,
    _CREATE_OPTION_QUOTE_OBSERVATIONS, _CREATE_SHADOW_CANDIDATES,
    _CREATE_SCANNER_CANDLE_OBSERVATIONS, _CREATE_SIGNAL_JOURNAL, _CREATE_TRADES,
    _CREATE_UNDERLYING_QUOTE_OBSERVATIONS,
)
from strategy_health.daily_scorecard import build_daily_scorecard
from strategy_health.event_tape import build_event_tape


class DailyEvidenceScorecardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        for ddl in (_CREATE_TRADES, _CREATE_BROKER_ORDER_EVENTS, _CREATE_SIGNAL_JOURNAL,
                    _CREATE_OPTION_QUOTE_OBSERVATIONS, _CREATE_SHADOW_CANDIDATES,
                    _CREATE_CANDIDATE_OPTION_QUOTE_OBSERVATIONS,
                    _CREATE_SCANNER_CANDLE_OBSERVATIONS,
                    _CREATE_UNDERLYING_QUOTE_OBSERVATIONS):
            self.conn.execute(ddl)

    def tearDown(self) -> None:
        self.conn.close()

    def _trade(self, account: str, trade_id: int, pnl: float) -> None:
        self.conn.execute("""
            INSERT INTO trades (id,ticker,contract_symbol,option_type,strike,expiry,
              contracts,entry_price,exit_price,entry_time,exit_time,realized_pnl,
              status,paper,strategy_id,broker_account_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (trade_id, "SPY", "SPY260828C00650000", "call", 650, "2026-08-28",
              1, 1.0, 1.0 + pnl / 100, "2026-08-26T10:00:00-04:00",
              "2026-08-26T10:30:00-04:00", pnl, "closed", 1, "TEST", account))

    def test_tape_excludes_other_accounts(self) -> None:
        self._trade("mine", 1, 25)
        self._trade("other", 2, 999)

        tape = build_event_tape(self.conn, "2026-08-26", "paper", "mine")

        self.assertTrue(tape["account_scoped"])
        self.assertEqual({1}, {event["trade_id"] for event in tape["events"]})

    def test_scorecard_combines_profit_decisions_execution_and_replay(self) -> None:
        self._trade("mine", 1, 50)
        self._trade("mine", 2, -25)
        for trade_id in (1, 2):
            self.conn.execute("""
                INSERT INTO option_quote_observations
                  (trade_id,observed_at,observed_minute,observation_kind,
                   contract_symbol,bid,ask,mid,last,fill_price,source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (trade_id, "2026-08-26T10:30:00-04:00", f"2026-08-26T10:{trade_id:02d}",
                  "exit", "SPY260828C00650000", 1, 1.02, 1.01, 1, 1, "test"))
        self.conn.execute("""
            INSERT INTO shadow_candidates
              (candidate_id,observed_at,ticker,strategy_id,direction,confidence,
               broker_account_id,final_outcome,linked_trade_id,direction_correct)
            VALUES ('c1','2026-08-26T10:00:00-04:00','SPY','TEST','bullish',.8,
                    'mine','entered',1,1)
        """)
        self.conn.execute("""
            INSERT INTO signal_journal
              (ts,ticker,strategy_id,direction,confidence,outcome,trade_id,broker_account_id)
            VALUES ('2026-08-26T10:00:00-04:00','SPY','TEST','bullish',.8,'entered',1,'mine')
        """)
        for attempt, trade_id in (("a1", 1), ("a2", 2)):
            self.conn.execute("""
                INSERT INTO broker_order_events
                  (event_time,attempt_id,broker_account_id,paper,event_type,ticker,
                   strategy_id,position_intent,filled_qty,linked_trade_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, ("2026-08-26T10:00:01-04:00", attempt, "mine", 1, "filled",
                  "SPY", "TEST", "buy_to_open", 1, trade_id))

        result = build_daily_scorecard(build_event_tape(
            self.conn, "2026-08-26", "paper", "mine",
        ))

        self.assertEqual(25, result["session_result"]["net_pnl"])
        self.assertEqual("B", result["session_result"]["grade"])
        self.assertEqual(2.0, result["trading"]["profit_factor"])
        self.assertEqual(100.0, result["execution"]["entry_fill_rate_pct"])
        self.assertEqual(100.0, result["decisions"]["directional_accuracy_pct"])
        self.assertTrue(result["replay"]["passed"])

    def test_no_account_returns_no_evidence_instead_of_blended_evidence(self) -> None:
        self._trade("mine", 1, 25)
        tape = build_event_tape(self.conn, "2026-08-26", "paper", None)
        self.assertFalse(tape["account_scoped"])
        self.assertEqual([], tape["events"])


if __name__ == "__main__":
    unittest.main()
