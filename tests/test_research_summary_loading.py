import json
import sqlite3
import unittest

from database.expiration_study import load
from trading.expiration_study_selection import PROFILE


class SummaryLoadingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            CREATE TABLE shadow_candidates(candidate_id TEXT, ticker TEXT,
                broker_account_id TEXT, observed_at TEXT);
            CREATE TABLE research_expiration_comparisons(candidate_id TEXT,
                profile_version TEXT, active INTEGER, state_json TEXT, selection_json TEXT);
        ''')
        for identity, account, day in [('a', 'one', '2026-09-23'),
                                      ('b', 'two', '2026-09-23'),
                                      ('c', 'one', '2026-08-01')]:
            state = dict(status='priced', bid=2.4, entry_ask=2, strategy_id='EXAMPLE',
                         premium_path={'partial_bid': 2.1, 'quote_count': 2},
                         meta={'large_entry_history': ['sample'] * 1000})
            self.conn.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?)',
                              (identity, 'SPY', account, day))
            self.conn.execute('INSERT INTO research_expiration_comparisons VALUES (?,?,?,?,?)',
                              (identity, PROFILE, 0, json.dumps(state),
                               json.dumps({'reason': None, 'unused_chain': ['contract'] * 1000})))

    def test_summary_preserves_values_without_loading_unused_entry_history(self):
        full = load(self.conn, account='one', cutoff='2026-09-01')
        compact = load(self.conn, account='one', cutoff='2026-09-01', summary_only=True)
        self.assertEqual([row['candidate_id'] for row in compact], ['a'])
        expected = {k: v for k, v in full[0]['state'].items() if k != 'meta'}
        self.assertEqual(compact[0]['state'], expected)
        self.assertEqual(compact[0]['selection']['reason'], full[0]['selection']['reason'])
        self.assertNotIn('state_json', compact[0])
        self.assertIn('meta', full[0]['state'])
        self.assertIn('unused_chain', full[0]['selection'])
        self.assertEqual(load(self.conn, account='one', active_only=True, summary_only=True), [])

    def test_missing_table_returns_no_summary(self):
        self.conn.execute('DROP TABLE research_expiration_comparisons')
        self.assertEqual(load(self.conn, account='one', summary_only=True), [])
