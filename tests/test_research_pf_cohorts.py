"""Exercise the actual matrix SQL/routing, not just a duplicate of its predicate."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch

from config.strategy_catalog import REVIEWED_STRATEGIES
from database.reference_contract_tests import STRATEGIES
from strategy_health.research_matrix import build_research_matrix
from strategy_health.pair_recommendations import assess, recommendations, decide
from trading.research_contract_selection import RESEARCH_CONTRACT_SOURCE, RESEARCH_CONTRACT_PROFILE_VERSION
from trading.research_versions import evidence_version


class ResearchPFCohortTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            CREATE TABLE shadow_candidates (
                candidate_id TEXT, observed_at TEXT, ticker TEXT, strategy_id TEXT,
                direction_correct INTEGER, directional_move_pct REAL, broker_account_id TEXT,
                trigger_bar TEXT, direction TEXT, metadata_json TEXT
            );
            CREATE TABLE candidate_option_quote_observations (
                candidate_id TEXT, observation_kind TEXT, bid REAL, ask REAL,
                observed_at TEXT, source TEXT, contract_symbol TEXT
            );
            CREATE TABLE candidate_contract_alternatives (
                candidate_id TEXT, contract_symbol TEXT, observation_kind TEXT,
                bid REAL, ask REAL, observed_at TEXT, policy_json TEXT, source TEXT
            );
            CREATE TABLE scanner_candle_observations (
                ticker TEXT, bar_time TEXT, broker_account_id TEXT
            );
        ''')

    def add(self, sid, ticker, identity, *, source=RESEARCH_CONTRACT_SOURCE,
            version=None, account='acct', end_delay=0, missing=False, mixed=False):
        rule = REVIEWED_STRATEGIES[sid]
        start = datetime.fromisoformat('2026-09-10T10:00:00-04:00')
        end = start + timedelta(minutes=rule.exit_minutes + end_delay)
        metadata = dict(strategy_version=version or evidence_version(sid, rule.version),
                        pa_consecutive_higher_lows=True)
        self.conn.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?,?,?)',
            (identity, start.isoformat(), ticker, sid, 1, 1.0, account,
             start.isoformat(), 'bullish', json.dumps(metadata)))
        self.conn.execute('INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?,?)',
            (identity, 'entry', 1.9, 2.0, start.isoformat(), source, ticker + '_CONTRACT'))
        if not missing:
            self.conn.execute('INSERT INTO candidate_option_quote_observations VALUES (?,?,?,?,?,?,?)',
                (identity, f'mark_{rule.exit_minutes}m', 1.8, 1.9, end.isoformat(), 'followup',
                 'OTHER_CONTRACT' if mixed else ticker + '_CONTRACT'))

    def matrix(self):
        @contextmanager
        def connection():
            yield self.conn
        settings = {'active_broker_account_id': 'acct', 'watchlist': [], 'research_strategy_ids': []}
        with patch('config.get_settings', return_value=settings), patch('database.get_conn', side_effect=connection), \
             patch('database._now_et', return_value=datetime(2026, 9, 11, 14)), \
             patch('scanner.state_io._read_daily_universe', return_value={}):
            return build_research_matrix(90)

    @staticmethod
    def pair(matrix, sid, ticker):
        strategy = next(r for r in matrix['strategies'] if r['strategy_id'] == sid)
        return next(p for p in strategy['pairs'] if p['ticker'] == ticker)

    def test_all_five_native_routes_use_same_research_cohort_as_other_tickers(self):
        for sid in STRATEGIES:
            native = sorted(REVIEWED_STRATEGIES[sid].tickers)[0]
            self.add(sid, native, sid + '-native')
            self.add(sid, 'META', sid + '-cross')
        matrix = self.matrix()
        for sid in STRATEGIES:
            with self.subTest(strategy=sid):
                native = sorted(REVIEWED_STRATEGIES[sid].tickers)[0]
                for ticker in (native, 'META'):
                    pair = self.pair(matrix, sid, ticker)
                    self.assertEqual(1, pair['option_results'])
                    self.assertEqual(0.0, pair['profit_factor'])
                    self.assertEqual(-23.3, pair['net_one_contract_pnl'])
                    self.assertEqual(RESEARCH_CONTRACT_PROFILE_VERSION, pair['research_contract_profile'])
                    self.assertEqual(1, pair['recommendation']['completed_trades'])

    def test_unrelated_account_version_profile_and_missing_or_late_quotes_do_not_count(self):
        sid = 'V2_TSLA_TWO_LEG_TREND_PULLBACK'
        cases = [dict(account='other'), dict(version='2.0.0'),
                 dict(source='tradier_observation_only_preview'), dict(source=''),
                 dict(missing=True), dict(end_delay=6), dict(mixed=True)]
        for index, options in enumerate(cases):
            ticker = f'TEST{index}'
            self.add(sid, ticker, ticker, **options)
        matrix = self.matrix()
        for index in range(1, len(cases)):
            with self.subTest(case=cases[index]):
                pair = self.pair(matrix, sid, f'TEST{index}')
                self.assertEqual(0, pair['option_results'])
                self.assertIsNone(pair['profit_factor'])
                self.assertEqual(0, pair['recommendation']['completed_trades'])
        self.assertFalse(any(p['ticker'] == 'TEST0' for s in matrix['strategies'] for p in s['pairs']))

    def test_order_preview_cannot_hide_same_trigger_research_candidate(self):
        sid = 'V2_SPY_TREND_CONT'
        self.add(sid, 'SPY', 'preview-first', source='tradier_observation_only_preview')
        self.add(sid, 'SPY', 'research-second')
        pair = self.pair(self.matrix(), sid, 'SPY')
        self.assertEqual(2, pair['raw_observations'])
        self.assertEqual(1, pair['legacy_option_profiles_ignored'])
        self.assertEqual(1, pair['option_results'])
        self.assertEqual(-23.3, pair['net_one_contract_pnl'])

    def test_research_contract_cannot_reenable_a_different_order_contract_policy(self):
        sid = 'V2_SPY_TREND_CONT'
        rule = REVIEWED_STRATEGIES[sid]
        start = datetime.fromisoformat('2026-09-10T10:00:00-04:00')
        evidence = assess([dict(id=str(i), entry_at=(start + timedelta(minutes=i*10)).isoformat(),
            exit_at=(start + timedelta(minutes=i*10+5)).isoformat(), pnl=p)
            for i, p in enumerate([20,20,-10,20,-10]*4)])
        matrix = {'strategies': [dict(strategy_id=sid, version=rule.version, display_name=rule.display_name,
            pairs=[dict(ticker='SPY', tradable=False, recommendation=evidence,
                        research_contract_profile=RESEARCH_CONTRACT_PROFILE_VERSION)])]}
        settings = {'paper_trading': True, rule.setting_key: True}
        with patch('config.strategy_catalog.reviewed_strategy_integrity_errors', return_value={}):
            result = recommendations(matrix, settings)['recommendations']
            self.assertEqual(1, len(result))
            self.assertFalse(result[0]['can_enable'])
            with self.assertRaises(ValueError):
                decide(matrix, settings, sid, 'SPY', 'enable', evidence['fingerprint'])


if __name__ == '__main__':
    unittest.main()
