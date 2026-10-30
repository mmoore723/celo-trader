"""Timing metadata is evidence only and must survive quote promotion."""
import json
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from database.schema import _init_db_at
from database.option_quotes import (record_candidate_option_quote,
    record_candidate_contract_alternative, promote_candidate_entry_quote, _quote_metadata,
    capture_due_candidate_option_quotes)


class QuoteTimingMetadataTests(unittest.TestCase):
    def test_individual_receipts_and_grace_boundary(self):
        for delays, expected in (((2, 8), (2, 8)), ((300, 301), (300,)),
                                 ((301, 302), ()), ((-1, -1), ())):
            with self.subTest(delays=delays), TemporaryDirectory() as directory:
                path = Path(directory) / 'receipts.db'
                _init_db_at(path)
                with sqlite3.connect(path) as conn:
                    conn.row_factory = sqlite3.Row
                    conn.execute("INSERT INTO shadow_candidates(candidate_id,observed_at,ticker,strategy_id,direction,confidence,broker_account_id) VALUES('c','2026-10-30T10:00:00','SPY','TEST','bullish',1,'acct')")
                    conn.commit()
                    entry = datetime.fromisoformat('2026-10-30T10:00:00-04:00')
                    sweep = entry + timedelta(minutes=30)
                    clock = iter(delays)
                    with patch('database.option_quotes.get_conn', return_value=conn):
                        record_candidate_option_quote(candidate_id='c', contract_symbol='PRIMARY',
                            observation_kind='entry', observed_at=entry,
                            quote={'bid':2,'ask':2.1}, source='test')
                        record_candidate_contract_alternative(candidate_id='c',
                            contract={'symbol':'ALT','bid':2,'ask':2.1},
                            observation_kind='entry', observed_at=entry)
                        count = capture_due_candidate_option_quotes(ticker='SPY',
                            observed_at=sweep, broker_account_id='acct',
                            quote_lookup=lambda symbol: {'bid':2,'ask':2.1},
                            receipt_clock=lambda: sweep + timedelta(seconds=next(clock)))
                    marks = []
                    for table in ('candidate_option_quote_observations', 'candidate_contract_alternatives'):
                        marks.extend(row[0] for row in conn.execute(
                            f"SELECT observed_at FROM {table} WHERE observation_kind='mark_30m'"))
                    self.assertEqual(count, len(expected))
                    self.assertEqual(marks, [(sweep + timedelta(seconds=delay)).replace(tzinfo=None).isoformat()
                                             for delay in expected])
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 0)

    def test_missing_and_invalid_fields_stay_unknown(self):
        value=json.loads(_quote_metadata({'quote_age_seconds':float('nan'),
                                         'bid_date':object()}))
        self.assertIsNone(value['quote_age_seconds'])
        self.assertIsNone(value['bid_date'])
        self.assertIsNone(value['quote_received_at'])

    def test_capture_and_promotion_preserve_original_metadata(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'test.db'
            _init_db_at(path)
            _init_db_at(path)
            with sqlite3.connect(path) as conn:
                conn.execute("INSERT INTO shadow_candidates(candidate_id,observed_at,ticker,strategy_id,direction,confidence) VALUES('c','2026-10-30T10:00:00','SPY','TEST','bullish',1)")
                conn.commit()
                now=datetime.fromisoformat('2026-10-30T10:00:00-04:00')
                quote={'bid':2,'ask':2.1,'quote_received_at':'2026-10-30T14:00:02+00:00',
                       'bid_date':1793368801000,'ask_date':1793368801500}
                with patch('database.option_quotes.get_conn',return_value=conn):
                    self.assertTrue(record_candidate_option_quote(candidate_id='c',contract_symbol='OLD',
                        observation_kind='entry',observed_at=now,quote=quote,source='test'))
                    newer={**quote,'quote_received_at':'2026-10-30T14:00:08+00:00'}
                    self.assertTrue(promote_candidate_entry_quote(candidate_id='c',contract_symbol='NEW',
                        observed_at=now,quote=newer,source='test'))
                    self.assertTrue(record_candidate_contract_alternative(candidate_id='c',
                        contract={'symbol':'ALT',**newer},observation_kind='entry',observed_at=now))
                primary=json.loads(conn.execute('SELECT quote_metadata_json FROM candidate_option_quote_observations').fetchone()[0])
                old=json.loads(conn.execute("SELECT quote_metadata_json FROM candidate_contract_alternatives WHERE contract_symbol='OLD'").fetchone()[0])
                self.assertEqual(primary['quote_received_at'],newer['quote_received_at'])
                self.assertEqual(old['quote_received_at'],quote['quote_received_at'])
                self.assertEqual(old['bid_date'],quote['bid_date'])
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0],0)

    def test_migration_does_not_backfill_legacy_metadata(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'legacy.db'
            _init_db_at(path)
            with sqlite3.connect(path) as conn:
                conn.execute('ALTER TABLE candidate_option_quote_observations DROP COLUMN quote_metadata_json')
                conn.execute("INSERT INTO candidate_option_quote_observations(candidate_id,observed_at,observation_kind,contract_symbol,source) VALUES('legacy','2026-09-01','entry','OLD','old')")
            _init_db_at(path)
            with sqlite3.connect(path) as conn:
                self.assertIsNone(conn.execute('SELECT quote_metadata_json FROM candidate_option_quote_observations').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
