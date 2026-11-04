from contextlib import contextmanager
import json
import sqlite3
import unittest
from unittest.mock import patch

from api.routes.learning import PracticeStart, start_practice
from api.routes.learning_guide import guide, VWAP


class LearningNavigationTests(unittest.TestCase):
    def test_vwap_reference_for_both_enabled_tickers_is_read_only(self):
        with patch('config.get_settings', return_value={}):
            for ticker in ('AMZN','TSLA'):
                result=guide(VWAP,ticker,'0.2.0')
                self.assertEqual(ticker,result['ticker'])
                self.assertEqual(4,len(result['steps']))
                self.assertIn('1%',result['steps'][0])
                self.assertIn('3:55',result['exit'])
                self.assertFalse(result['order_authority'])

    def test_empty_practice_is_not_a_404_and_does_not_mix_pair_or_account(self):
        conn=sqlite3.connect(':memory:'); conn.row_factory=sqlite3.Row
        self.addCleanup(conn.close)
        conn.executescript('''CREATE TABLE learning_examples(strategy_id TEXT,published INTEGER,evidence_json TEXT);
            CREATE TABLE shadow_candidates(candidate_id TEXT,broker_account_id TEXT);''')
        for key,ticker,version,account in [('other-ticker','TSLA','0.2.0','a'),
                                          ('other-version','AMZN','old','a'),
                                          ('other-account','AMZN','0.2.0','b')]:
            conn.execute('INSERT INTO learning_examples VALUES (?,1,?)',(VWAP,json.dumps(dict(
                example_id=key,ticker=ticker,strategy_version=version,practice_eligible=True))))
            conn.execute('INSERT INTO shadow_candidates VALUES (?,?)',(key,account))
        @contextmanager
        def connection():
            yield conn
        with patch('database.get_conn',connection),patch('api.routes.learning._account_scope',return_value=('broker_account_id=?',('a',))):
            result=start_practice(PracticeStart(strategy_id=VWAP,ticker='AMZN',version='0.2.0'))
        self.assertEqual('empty',result['status'])
        self.assertNotIn('session_id',result)
