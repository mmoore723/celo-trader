"""Regression checks with deliberately different trade IDs and quote-row IDs."""
import unittest

from strategy_health.event_tape import _event, build_event_tape
from strategy_health.golden_replay import replay_event_tape
from tests import test_daily_evidence_scorecard as scorecard_fixture


class EventTapeQuoteLinksTests(unittest.TestCase):
    setUp = scorecard_fixture.DailyEvidenceScorecardTests.setUp
    tearDown = scorecard_fixture.DailyEvidenceScorecardTests.tearDown
    _trade = scorecard_fixture.DailyEvidenceScorecardTests._trade

    def _quote(self, quote_id, trade_id, kind="exit"):
        self.conn.execute("""
            INSERT INTO option_quote_observations
              (id,trade_id,observed_at,observed_minute,observation_kind,
               contract_symbol,bid,ask,source)
            VALUES (?,?,'2026-08-26T10:30:00-04:00','2026-08-26T10:30',?,
                    'SPY260828C00650000',1.1,1.12,'test')
        """, (quote_id,trade_id,kind))

    def test_quote_row_id_is_not_the_trade_identity(self):
        self._trade("mine",209,10)
        self._quote(700,209)
        tape = build_event_tape(self.conn,"2026-08-26","paper","mine")
        quote = next(e for e in tape["events"] if e["kind"]=="trade_quote")
        self.assertEqual("trade_quote:700",quote["event_id"])
        self.assertEqual(700,quote["payload"]["id"])
        self.assertEqual(209,quote["trade_id"])
        self.assertEqual(209,quote["payload"]["trade_id"])

    def test_closed_trade_links_to_its_differently_numbered_exit_quote(self):
        self._trade("mine",209,10)
        self._quote(700,209)
        result = replay_event_tape(build_event_tape(self.conn,"2026-08-26","paper","mine")["events"])
        check = next(c for c in result["checks"] if c["name"]=="closed trades have exit quotes")
        self.assertEqual(1,check["proven"])
        self.assertTrue(result["passed"])

    def test_quote_cannot_stand_in_for_an_absent_trade_record(self):
        events = [
            _event("signal","1","2026-08-26T10:00:00",{"outcome":"entered","trade_id":209}),
            _event("trade_quote","700","2026-08-26T10:30:00",
                   {"id":700,"trade_id":209,"observation_kind":"exit"}),
        ]
        result = replay_event_tape(events)
        self.assertFalse(result["passed"])
        self.assertEqual(0,result["checks"][0]["proven"])

    def test_broker_fill_cannot_link_to_a_quote_instead_of_a_trade(self):
        events = [
            _event("order","1","2026-08-26T10:00:00",{"event_type":"filled","trade_id":700}),
            _event("trade_quote","700","2026-08-26T10:30:00",
                   {"id":700,"trade_id":209,"observation_kind":"exit"}),
        ]
        result = replay_event_tape(events)
        self.assertFalse(result["passed"])
        self.assertEqual(0,result["checks"][2]["proven"])

    def test_other_account_quotes_do_not_supply_my_missing_exit(self):
        self._trade("mine",209,10)
        self._trade("other",210,999)
        self._quote(209,210)
        tape = build_event_tape(self.conn,"2026-08-26","paper","mine")
        self.assertFalse(any(e["kind"]=="trade_quote" for e in tape["events"]))
        self.assertFalse(replay_event_tape(tape["events"])["passed"])

    def test_many_marks_do_not_inflate_exit_coverage(self):
        self._trade("mine",209,10)
        self._trade("mine",210,-20)
        self._quote(700,209,"entry")
        self._quote(701,209,"mark")
        self._quote(702,209,"exit")
        result = replay_event_tape(build_event_tape(self.conn,"2026-08-26","paper","mine")["events"])
        check = next(c for c in result["checks"] if c["name"]=="closed trades have exit quotes")
        self.assertEqual(2,check["expected"])
        self.assertEqual(1,check["proven"])
        self.assertEqual(50,check["coverage_pct"])


if __name__ == "__main__":
    unittest.main()
