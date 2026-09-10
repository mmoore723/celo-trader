"""Fixed exits start at the priced entry, not the earlier scanner signal."""
from datetime import datetime
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from database.schema import _init_db_at
from database.option_quotes import (capture_due_candidate_option_quotes,
    record_candidate_option_quote, record_candidate_contract_alternative)
from config.strategy_catalog import REVIEWED_STRATEGIES
from strategy_health.exit_measurement import exit_measurement, _EXACT_TIMED_EXITS
from strategy_health.research_matrix import _quote_profit


def stamp(clock):
    return datetime.fromisoformat(f"2026-09-09T{clock}-04:00")


class TimedExitAnchorTests(unittest.TestCase):
    def test_all_five_native_horizons_match_and_other_horizons_do_not(self):
        for strategy_id in _EXACT_TIMED_EXITS:
            minutes = REVIEWED_STRATEGIES[strategy_id].exit_minutes
            self.assertEqual('strategy_exit', exit_measurement(strategy_id, minutes)['kind'])
            other = 90 if minutes == 30 else 30
            self.assertEqual('timed_comparison', exit_measurement(strategy_id, other)['kind'])

    def test_delayed_primary_and_alternative_have_separate_entry_clocks(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.db'
            _init_db_at(path)
            conn = sqlite3.connect(path)
            self.addCleanup(conn.close)
            conn.row_factory = sqlite3.Row
            conn.execute("""INSERT INTO shadow_candidates
                (candidate_id, observed_at, ticker, strategy_id, direction,
                 confidence, tier, broker_account_id)
                VALUES ('a','2026-09-09T10:00:00-04:00','META',
                        'V2_SPY_AFTERNOON_FVG','bullish',.8,'main','acct')""")
            conn.commit()
            with patch('database.option_quotes.get_conn', return_value=conn):
                record_candidate_option_quote(candidate_id='a', contract_symbol='PRIMARY',
                    observation_kind='entry', observed_at=stamp('10:02:00'),
                    quote={'bid':1.9,'ask':2}, source='test')
                record_candidate_contract_alternative(candidate_id='a',
                    contract={'symbol':'ALT','bid':1.9,'ask':2},
                    observation_kind='entry', observed_at=stamp('10:04:00'), source='test')
                def sweep(clock, account='acct'):
                    return capture_due_candidate_option_quotes(ticker='META',
                        observed_at=stamp(clock), broker_account_id=account,
                        quote_lookup=lambda symbol: {'symbol':symbol,'bid':3,'ask':3.1})
                self.assertEqual(0, sweep('10:30:00'))
                self.assertEqual(0, sweep('10:32:00', 'other'))
                self.assertEqual(1, sweep('10:32:00'))
                self.assertEqual(1, sweep('10:34:00'))
                self.assertEqual(0, sweep('10:34:00'))
                self.assertEqual(0, sweep('11:10:00'))  # Missed 60-minute windows.
            for table, entry_time, mark_time in (
                ('candidate_option_quote_observations','10:02:00','10:32:00'),
                ('candidate_contract_alternatives','10:04:00','10:34:00'),
            ):
                mark = conn.execute(f"SELECT * FROM {table} WHERE observation_kind='mark_30m'").fetchone()
                self.assertEqual(stamp(mark_time).replace(tzinfo=None).isoformat(), mark['observed_at'])
                self.assertEqual(96.7, _quote_profit({'entry_ask':2,'bid_30':mark['bid'],
                    'entry_quote_at':stamp(entry_time).replace(tzinfo=None).isoformat(),
                    'mark_30_at':mark['observed_at']}, 30))
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0])
