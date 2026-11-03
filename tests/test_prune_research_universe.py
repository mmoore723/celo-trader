import sqlite3
import unittest
from research.jobs.prune_research_universe import prune


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.executescript('''
        CREATE TABLE shadow_candidates(candidate_id TEXT PRIMARY KEY,ticker TEXT,linked_trade_id INTEGER);
        CREATE TABLE candidate_option_quote_observations(candidate_id TEXT REFERENCES shadow_candidates(candidate_id),ask REAL);
        CREATE TABLE trades(candidate_id TEXT,ticker TEXT);
        CREATE TABLE scanner_candle_observations(ticker TEXT);
        INSERT INTO shadow_candidates VALUES('keep','SPY',NULL),('remove','XYZ',NULL);
        INSERT INTO candidate_option_quote_observations VALUES('keep',2),('remove',3);
        INSERT INTO trades VALUES('other','XYZ');
        INSERT INTO scanner_candle_observations VALUES('SPY'),('XYZ');
        ''')

    def test_dry_run_is_rolled_back(self):
        r = prune(self.c,['SPY'])
        self.assertEqual(['XYZ'],r['removed_tickers'])
        self.assertEqual(2,self.c.execute('SELECT count(*) FROM shadow_candidates').fetchone()[0])

    def test_apply_preserves_trades_and_retained_evidence(self):
        prune(self.c,['SPY'],apply=True)
        self.assertEqual([('keep',2)],self.c.execute('SELECT * FROM candidate_option_quote_observations').fetchall())
        self.assertEqual([('other','XYZ')],self.c.execute('SELECT * FROM trades').fetchall())
        self.assertEqual([('SPY',)],self.c.execute('SELECT * FROM scanner_candle_observations').fetchall())
        self.assertEqual([],self.c.execute('PRAGMA foreign_key_check').fetchall())

    def test_linked_trade_refuses_entire_cleanup(self):
        self.c.execute("INSERT INTO trades VALUES('remove','XYZ')")
        self.c.commit()
        with self.assertRaises(ValueError): prune(self.c,['SPY'],apply=True)
        self.assertEqual(2,self.c.execute('SELECT count(*) FROM shadow_candidates').fetchone()[0])

    def test_empty_keep_refused(self):
        with self.assertRaises(ValueError): prune(self.c,[],apply=True)
