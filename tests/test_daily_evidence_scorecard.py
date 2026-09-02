from __future__ import annotations

import sqlite3
import unittest

from database.schema import (
    _CREATE_BROKER_ORDER_EVENTS, _CREATE_CANDIDATE_CONTRACT_ALTERNATIVES,
    _CREATE_CANDIDATE_OPTION_QUOTE_OBSERVATIONS,
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
                    _CREATE_CANDIDATE_CONTRACT_ALTERNATIVES,
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
            self.conn.executemany("""
                INSERT INTO broker_order_events
                  (event_time,attempt_id,broker,broker_account_id,paper,event_type,ticker,
                   strategy_id,side,position_intent,filled_qty,limit_price,fill_price,linked_trade_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                ("2026-08-26T10:00:00-04:00", attempt, "tradier", "mine", 1,
                 "authoritative_quote", "SPY", "TEST", "buy", "buy_to_open", 1, 1.00, None, trade_id),
                ("2026-08-26T10:00:01-04:00", attempt, "tradier", "mine", 1,
                 "filled", "SPY", "TEST", "buy", "buy_to_open", 1, 1.00, 1.01, trade_id),
                ("2026-08-26T10:00:01-04:00", attempt, "tradier", "mine", 1,
                 "execution_summary", "SPY", "TEST", "buy", "buy_to_open", 1, 1.00, 1.01, trade_id),
            ])

        result = build_daily_scorecard(build_event_tape(
            self.conn, "2026-08-26", "paper", "mine",
        ))

        self.assertEqual(25, result["session_result"]["net_pnl"])
        self.assertEqual("B", result["session_result"]["grade"])
        self.assertEqual(2.0, result["trading"]["profit_factor"])
        self.assertEqual(100.0, result["execution"]["entry_fill_rate_pct"])
        self.assertEqual(2, result["execution"]["quote_to_fill"]["paired_fills"])
        self.assertEqual(2.0, result["execution"]["quote_to_fill"]["signed_adverse_slippage_dollars"])
        self.assertEqual(100.0, result["decisions"]["directional_accuracy_pct"])
        self.assertTrue(result["replay"]["passed"])

    def test_no_account_returns_no_evidence_instead_of_blended_evidence(self) -> None:
        self._trade("mine", 1, 25)
        tape = build_event_tape(self.conn, "2026-08-26", "paper", None)
        self.assertFalse(tape["account_scoped"])
        self.assertEqual([], tape["events"])

    def test_unfilled_order_uses_exact_contract_and_strategy_hold(self) -> None:
        import json

        candidate_id = "missed-spy"
        contract = "SPY260904C00650000"
        strategy = "V2_SPY_TREND_CONT"
        self.conn.execute("""
            INSERT INTO shadow_candidates
              (candidate_id,observed_at,ticker,strategy_id,direction,confidence,
               broker_account_id,final_outcome)
            VALUES (?, '2026-08-26T11:40:00-04:00', 'SPY', ?, 'bullish', .8,
                    'mine', 'blocked')
        """, (candidate_id, strategy))
        context = {"order_intent": {
            "candidate_id": candidate_id, "contract_symbol": contract,
            "strategy_id": strategy, "quantity": 2, "status": "price_not_reached",
        }}
        self.conn.execute("""
            INSERT INTO signal_journal
              (ts,ticker,strategy_id,direction,confidence,outcome,reason_code,
               context_json,broker_account_id)
            VALUES ('2026-08-26T11:40:45-04:00','SPY',?,'bullish',.8,'blocked',
                    'entry_price_not_reached',?,'mine')
        """, (strategy, json.dumps(context)))
        for kind, bid, ask, observed in (
            ("entry", 3.67, 3.68, "2026-08-26T11:40:00-04:00"),
            ("mark_30m", 4.14, 4.15, "2026-08-26T12:10:00-04:00"),
        ):
            self.conn.execute("""
                INSERT INTO candidate_contract_alternatives
                  (candidate_id,contract_symbol,observed_at,observation_kind,
                   bid,ask,mid,source)
                VALUES (?,?,?,?,?,?,?,'test')
            """, (candidate_id, contract, observed, kind, bid, ask, (bid + ask) / 2))

        result = build_daily_scorecard(build_event_tape(
            self.conn, "2026-08-26", "paper", "mine",
        ))
        planned = result["decisions"]["missed_executable_moves"]["planned_hold"]

        self.assertEqual(1, planned["measured"])
        self.assertEqual(1, planned["profitable"])
        self.assertEqual(92.0, planned["estimated_pnl_dollars"])


if __name__ == "__main__":
    unittest.main()
