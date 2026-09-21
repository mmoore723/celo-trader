from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import unittest
from unittest.mock import patch

from trading.tsla_giveback_exit import giveback_exit, evaluate_tsla_giveback, STATE_KEY, EXIT_REASON


class GivebackTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 15, tzinfo=timezone.utc)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE trades(id INTEGER, status TEXT, paper INTEGER, broker_account_id TEXT, strategy_context_json TEXT)")
        self.conn.execute("INSERT INTO trades VALUES (1,'open',1,'account','{\"signal\":42}')")
        self.conn.commit()
        self.trade = dict(id=1, strategy_id="V2_TSLA_TWO_LEG_TREND_PULLBACK", ticker="TSLA", paper=1,
                          broker_account_id="account", contract_symbol="contract", entry_price=10)

    def tearDown(self):
        self.conn.close()

    @contextmanager
    def connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def call(self, bid, minutes=0, **changes):
        now = self.now + timedelta(minutes=minutes)
        quote = dict(symbol="contract", bid=bid, ask=bid+0.1, quote_received_at=now.isoformat(), quote_age_seconds=0)
        quote.update(changes)
        with patch("database.get_conn", self.connection):
            return evaluate_tsla_giveback(self.trade, self.now-timedelta(minutes=10), now, quote)

    def test_exact_activation_and_strict_giveback(self):
        s = {}
        self.assertFalse(giveback_exit(s,10,10.64,self.now)[0])
        self.assertFalse(s.get("armed"))
        self.assertFalse(giveback_exit(s,10,10.65,self.now+timedelta(minutes=1))[0])
        self.assertTrue(s["armed"])
        self.assertFalse(giveback_exit(s,10,10.4225,self.now+timedelta(minutes=2))[0])
        self.assertTrue(giveback_exit(s,10,10.42,self.now+timedelta(minutes=3))[0])

    def test_peak_grows_and_latch_survives_rebound(self):
        s = {}
        giveback_exit(s,10,11,self.now)
        giveback_exit(s,10,12,self.now+timedelta(minutes=1))
        self.assertTrue(giveback_exit(s,10,11.29,self.now+timedelta(minutes=2))[0])
        self.assertTrue(giveback_exit(s,10,13,self.now+timedelta(minutes=3))[0])

    def test_once_per_minute_and_no_fifteen_percent_trigger(self):
        s = {}
        giveback_exit(s,2,2.5,self.now)
        self.assertFalse(s.get("armed"))
        giveback_exit(s,2,3,self.now+timedelta(seconds=1))
        self.assertFalse(s.get("armed"))

    def test_restart_restores_peak_and_pending(self):
        self.call(11)
        self.assertEqual(self.call(10.64,1),(True,EXIT_REASON))
        self.assertEqual(self.call(12,2),(True,EXIT_REASON))
        saved=json.loads(self.conn.execute("SELECT strategy_context_json FROM trades").fetchone()[0])
        self.assertEqual(saved["signal"],42)
        self.assertTrue(saved[STATE_KEY]["pending"])

    def test_invalid_quotes_do_not_arm(self):
        for changes in ({"quote_age_seconds":61},{"quote_age_seconds":None},{"ask":10},
                        {"symbol":"wrong"},{"quote_received_at":(self.now+timedelta(seconds=1)).isoformat()}):
            self.assertFalse(self.call(11,**changes)[0])
        saved=json.loads(self.conn.execute("SELECT strategy_context_json FROM trades").fetchone()[0])
        self.assertNotIn(STATE_KEY,saved)

    def test_other_strategy_ticker_and_live_excluded(self):
        for change in ({"paper":0},{"ticker":"SPY"},{"strategy_id":"V2_ORB_PULLBACK"}):
            with patch("database.get_conn") as db:
                self.assertIsNone(evaluate_tsla_giveback({**self.trade,**change},self.now-timedelta(minutes=1),self.now,None))
                db.assert_not_called()

    def test_account_isolation(self):
        self.trade["broker_account_id"]="other"
        self.assertFalse(self.call(11)[0])

    def test_timer_remains_ninety_minutes(self):
        from trading.v2_orb_paper_exit import evaluate_v2_orb_paper_exit
        start=self.now-timedelta(minutes=90)
        self.assertTrue(evaluate_v2_orb_paper_exit(start,self.now,self.trade["strategy_id"])[0])

    def test_market_close_only_for_approved_paper_signal(self):
        from trading.tsla_giveback_exit import use_giveback_market_order
        self.assertTrue(use_giveback_market_order(self.trade,EXIT_REASON,True))
        self.assertFalse(use_giveback_market_order(self.trade,EXIT_REASON,False))
        self.assertFalse(use_giveback_market_order(self.trade,"native_exit_deadline",True))
        self.assertFalse(use_giveback_market_order({**self.trade,"ticker":"SPY"},EXIT_REASON,True))
        self.assertFalse(use_giveback_market_order({**self.trade,"paper":0},EXIT_REASON,True))


if __name__ == "__main__":
    unittest.main()
