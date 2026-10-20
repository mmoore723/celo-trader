from contextlib import contextmanager
import json
import sqlite3
import unittest
from unittest.mock import patch

from strategy_health.closed_trade_evidence import summarize, build_closed_trade_evidence


def trade(identity=1, **updates):
    return dict(dict(id=identity, parent_trade_id=None, candidate_strategy_version='2.1.0',
        status='closed', realized_pnl=-230, entry_time='2026-09-10T10:36:00-04:00',
        exit_time='2026-09-10T12:06:00-04:00'), **updates)


class ClosedTradeEvidenceTests(unittest.TestCase):
    def test_two_losses_update_current_pf_without_old_winners(self):
        result = summarize([trade(), trade(2), trade(3, candidate_strategy_version='2.0.0', realized_pnl=1000)], '2.1.0')
        self.assertEqual(2, result['completed_trades'])
        self.assertEqual(0, result['profit_factor'])
        self.assertEqual(-460, result['realized_pnl'])
        self.assertEqual(1, result['exclusions']['different_or_unknown_version'])

    def test_pf_uses_actual_position_pnl_not_one_contract_research(self):
        result = summarize([trade(realized_pnl=300), trade(2, realized_pnl=-100)], '2.1.0')
        self.assertEqual(3, result['profit_factor'])
        self.assertEqual(200, result['realized_pnl'])

    def test_empty_or_unidentified_history_is_not_zero_pnl(self):
        for rows in ([], [trade(candidate_strategy_version=None)]):
            result = summarize(rows, '2.1.0')
            self.assertIsNone(result['profit_factor'])
            self.assertIsNone(result['realized_pnl'])
            self.assertIsNone(result['first_entry_date'])

    def test_partial_legs_form_one_completed_trade(self):
        result = summarize([trade(realized_pnl=-100), trade(2, parent_trade_id=1, realized_pnl=150)], '2.1.0')
        self.assertEqual(1, result['completed_trades'])
        self.assertEqual(50, result['realized_pnl'])
        self.assertEqual('infinite', result['profit_factor'])

    def test_open_runner_and_missing_parent_cannot_be_completed(self):
        result = summarize([trade(status='open'), trade(2, parent_trade_id=1), trade(3, parent_trade_id=99)], '2.1.0')
        self.assertEqual(0, result['completed_trades'])
        self.assertEqual({'still_open': 1, 'missing_parent': 1}, result['exclusions'])

    def test_invalid_or_early_exit_is_reported_not_scored(self):
        for updates in (dict(realized_pnl=None), dict(realized_pnl=float('nan')),
                        dict(exit_time='bad'), dict(exit_time='2026-09-10T10:00:00-04:00')):
            with self.subTest(updates=updates):
                result = summarize([trade(**updates)], '2.1.0')
                self.assertEqual({'incomplete_record': 1}, result['exclusions'])

    def test_dates_use_market_timezone_not_utc_calendar(self):
        result = summarize([trade(entry_time='2026-09-10T23:00:00Z', exit_time='2026-09-11T00:01:00Z')], '2.1.0')
        self.assertEqual('2026-09-10', result['last_exit_date'])

    def test_no_active_account_never_reads_all_accounts(self):
        with patch('config.get_settings', return_value={}), patch('database.connection._conn_for_mode') as connection:
            self.assertFalse(build_closed_trade_evidence()['available'])
            connection.assert_not_called()

    def test_database_mode_account_and_candidate_lineage_are_scoped(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript('''
          CREATE TABLE trades (id INTEGER,parent_trade_id INTEGER,strategy_id TEXT,ticker TEXT,status TEXT,
            entry_time TEXT,exit_time TEXT,realized_pnl REAL,candidate_id TEXT,broker_account_id TEXT,paper INTEGER);
          CREATE TABLE shadow_candidates (candidate_id TEXT,broker_account_id TEXT,strategy_id TEXT,ticker TEXT,metadata_json TEXT);
        ''')
        sid = 'V2_TSLA_TWO_LEG_TREND_PULLBACK'
        from config.strategy_catalog import REVIEWED_STRATEGIES
        version = REVIEWED_STRATEGIES[sid].version
        for i, account, paper, candidate_account, meta in (
            (1,'acct',1,'acct',json.dumps({'strategy_version':version})),
            (2,'other',1,'other',json.dumps({'strategy_version':version})),
            (3,'acct',0,'acct',json.dumps({'strategy_version':version})),
            (4,'acct',1,'other',json.dumps({'strategy_version':version})),
            (5,'acct',1,'acct','invalid json')):
            conn.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (i,None,sid,'TSLA','closed','2026-09-10T10:00:00','2026-09-10T11:30:00',-230,str(i),account,paper))
            conn.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?,?)',(str(i),candidate_account,sid,'TSLA',meta))
        @contextmanager
        def connection(mode):
            self.assertEqual('paper',mode)
            yield conn
        with patch('config.get_settings', return_value={'active_broker_account_id':'acct','paper_trading':True}), \
             patch('database.connection._conn_for_mode',side_effect=connection):
            result = build_closed_trade_evidence()
        pair = next(s for s in result['strategies'] if s['strategy_id']==sid)['pairs'][0]
        self.assertEqual(1,pair['completed_trades'])
        self.assertEqual(-230,pair['realized_pnl'])
        self.assertEqual(2,pair['exclusions']['different_or_unknown_version'])


if __name__ == '__main__':
    unittest.main()
