from __future__ import annotations

import unittest

from research.jobs.audit_broker_execution import summarize


class BrokerExecutionAuditTests(unittest.TestCase):
    def test_separates_bounded_miss_from_adverse_market_fill(self) -> None:
        rows = [
            {"id": 1, "event_time": "2026-08-20T10:00:00", "attempt_id": "entry", "event_type": "submit_attempt", "side": "buy", "position_intent": "buy_to_open", "requested_qty": 2, "limit_price": 4.00, "is_issue": 0},
            {"id": 2, "event_time": "2026-08-20T10:00:20", "attempt_id": "entry", "event_type": "entry_expired_no_fill", "side": "buy", "position_intent": "buy_to_open", "filled_qty": 0, "status": "canceled", "is_issue": 0},
            {"id": 3, "event_time": "2026-08-20T11:00:00", "attempt_id": "exit", "event_type": "submit_attempt", "side": "sell", "position_intent": "sell_to_close", "requested_qty": 2, "limit_price": 4.25, "is_issue": 0},
            {"id": 4, "event_time": "2026-08-20T11:00:20", "attempt_id": "exit", "event_type": "fallback_acknowledged", "side": "sell", "position_intent": "sell_to_close", "is_issue": 0},
            {"id": 5, "event_time": "2026-08-20T11:00:21", "attempt_id": "exit", "event_type": "filled", "side": "sell", "position_intent": "sell_to_close", "filled_qty": 2, "fill_price": 4.09, "is_issue": 0},
        ]

        report = summarize(rows)

        self.assertEqual(0, report["by_intent"]["buy_to_open"]["filled_attempts"])
        self.assertEqual(1, report["by_intent"]["sell_to_close"]["filled_attempts"])
        self.assertEqual(1, report["by_intent"]["sell_to_close"]["market_fallback_attempts"])
        self.assertAlmostEqual(32.0, report["by_intent"]["sell_to_close"]["adverse_slippage_dollars"])

    def test_tradier_reference_and_latency_are_reported_for_alpaca_fill(self) -> None:
        rows = [
            {"id": 1, "event_time": "2026-08-22T10:00:00", "attempt_id": "entry", "broker": "alpaca", "event_type": "authoritative_quote", "side": "buy", "position_intent": "buy_to_open", "requested_qty": 2, "limit_price": 1.15, "latency_ms": 42.5, "is_issue": 0},
            {"id": 2, "event_time": "2026-08-22T10:00:01", "attempt_id": "entry", "broker": "alpaca", "event_type": "submit_attempt", "side": "buy", "position_intent": "buy_to_open", "requested_qty": 2, "limit_price": 1.10, "is_issue": 0},
            {"id": 3, "event_time": "2026-08-22T10:00:01", "attempt_id": "entry", "broker": "alpaca", "event_type": "acknowledged", "side": "buy", "position_intent": "buy_to_open", "latency_ms": 120.0, "is_issue": 0},
            {"id": 4, "event_time": "2026-08-22T10:00:03", "attempt_id": "entry", "broker": "alpaca", "event_type": "filled", "side": "buy", "position_intent": "buy_to_open", "filled_qty": 2, "fill_price": 1.16, "is_issue": 0},
            {"id": 5, "event_time": "2026-08-22T10:00:03", "attempt_id": "entry", "broker": "alpaca", "event_type": "execution_summary", "side": "buy", "position_intent": "buy_to_open", "filled_qty": 2, "limit_price": 1.15, "fill_price": 1.16, "latency_ms": 2120.0, "is_issue": 0},
        ]

        attempt = summarize(rows)["attempts"][0]

        self.assertEqual("tradier", attempt["reference_source"])
        self.assertEqual(42.5, attempt["quote_latency_ms"])
        self.assertEqual(120.0, attempt["submit_ack_latency_ms"])
        self.assertEqual(2120.0, attempt["submit_to_fill_latency_ms"])
        self.assertAlmostEqual(2.0, attempt["adverse_slippage_dollars"])
        self.assertEqual("alpaca", attempt["broker"])

    def test_broker_buckets_do_not_blend_alpaca_and_tradier(self) -> None:
        rows = [
            {"id": 1, "event_time": "2026-08-22T10:00:00", "attempt_id": "a", "broker": "alpaca", "event_type": "submit_attempt", "side": "buy", "position_intent": "buy_to_open", "requested_qty": 1, "limit_price": 1.0, "is_issue": 0},
            {"id": 2, "event_time": "2026-08-22T10:00:01", "attempt_id": "a", "broker": "alpaca", "event_type": "filled", "side": "buy", "position_intent": "buy_to_open", "filled_qty": 1, "fill_price": 1.0, "is_issue": 0},
            {"id": 3, "event_time": "2026-08-22T10:01:00", "attempt_id": "t", "broker": "tradier", "event_type": "submit_attempt", "side": "buy", "position_intent": "buy_to_open", "requested_qty": 1, "limit_price": 1.0, "is_issue": 0},
            {"id": 4, "event_time": "2026-08-22T10:01:01", "attempt_id": "t", "broker": "tradier", "event_type": "terminal_no_fill", "side": "buy", "position_intent": "buy_to_open", "filled_qty": 0, "is_issue": 0},
        ]

        report = summarize(rows)

        self.assertEqual(100.0, report["by_broker_and_intent"]["alpaca"]["buy_to_open"]["fill_rate_pct"])
        self.assertEqual(0.0, report["by_broker_and_intent"]["tradier"]["buy_to_open"]["fill_rate_pct"])
        self.assertEqual(50.0, report["by_intent"]["buy_to_open"]["fill_rate_pct"])


if __name__ == "__main__":
    unittest.main()
