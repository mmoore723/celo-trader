import sqlite3
import unittest
from database.research_quote_diagnostics import record


class QuoteDiagnosticsTests(unittest.TestCase):
    def test_invalid_close_quote_preserved_not_used_as_fill(self):
        with sqlite3.connect(':memory:') as conn:
            args=dict(candidate_id='a',protocol='p',contract='XYZ',decision='2026-11-03T16:00:00',
                      requested='2026-11-03T16:00:01',received='2026-11-03T16:00:02',
                      deadline='2026-11-03T16:05:00',quote=dict(symbol='XYZ',source_symbol='XYZ',
                      bid=1.2,ask=1.3,bid_date='2026-11-03T15:59:59',bidsize=2))
            self.assertEqual('bid_before_decision',record(conn,**args))
            record(conn,**args)
            self.assertEqual(1,conn.execute('SELECT count(*) FROM research_exit_quote_diagnostics').fetchone()[0])
            args['quote']['bid_date']='2026-11-03T16:00:01'
            self.assertEqual('accepted',record(conn,**args))
            self.assertEqual(2,conn.execute('SELECT count(*) FROM research_exit_quote_diagnostics').fetchone()[0])
            self.assertEqual('receipt_after_deadline',record(conn,**{**args,'received':'2026-11-03T16:06:00'}))
