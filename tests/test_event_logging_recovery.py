import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from database.events import log_event
from trading.research_order_exit import evaluate_exit


class EventLoggingRecoveryTests(unittest.TestCase):
    def test_real_writer_lock_does_not_abort_exit_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'events.db'
            writer = sqlite3.connect(path)
            self.addCleanup(writer.close)
            writer.execute('CREATE TABLE system_events (ts, level, component, message)')
            writer.commit()
            writer.execute('BEGIN IMMEDIATE')

            @contextmanager
            def connection():
                conn = sqlite3.connect(path, timeout=.01)
                try:
                    with conn:
                        yield conn
                finally:
                    conn.close()

            trade = {'strategy_id':'RESEARCH_FAILED_RANGE_V2',
                     'strategy_context_json':json.dumps({
                         'strategy_version':'2.1.0.research.2',
                         'research_order_route':'exact_research_v1'})}
            entry = datetime(2026,10,13,10,8,12,tzinfo=ZoneInfo('America/New_York'))
            with patch('database.events.get_conn',connection), self.assertLogs('celo_trader',level='INFO') as captured:
                log_event('ERROR','trading_logic','position management retry')
                decision = evaluate_exit(trade,entry,entry+timedelta(minutes=30),None)
            self.assertEqual(decision,(True,'research_failed_range_30m'))
            self.assertTrue(any('position management retry' in line for line in captured.output))
            self.assertTrue(any('database write failed' in line for line in captured.output))
            writer.rollback()
            with patch('database.events.get_conn',connection):
                log_event('INFO','trading_logic','database recovered')
            self.assertEqual(writer.execute('SELECT message FROM system_events').fetchall(),[('database recovered',)])

    def test_connection_setup_failure_still_mirrors_event(self):
        with patch('database.events.get_conn',side_effect=sqlite3.OperationalError('database is locked')), \
             self.assertLogs('celo_trader',level='WARNING') as captured:
            log_event('WARNING','trading_logic','retry next tick')
        self.assertTrue(any('retry next tick' in line for line in captured.output))

    def test_connection_setup_failure_closes_connection(self):
        from database.connection import get_conn
        conn = Mock()
        conn.execute.side_effect = sqlite3.OperationalError('database is locked')
        with patch('database.connection.get_db_path',return_value='unused'), \
             patch('database.connection.sqlite3.connect',return_value=conn):
            with self.assertRaises(sqlite3.OperationalError):
                with get_conn():
                    self.fail('Connection setup should fail')
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_non_audit_database_errors_still_propagate(self):
        from database.connection import get_conn
        conn = Mock()
        with patch('database.connection.get_db_path',return_value='unused'), \
             patch('database.connection.sqlite3.connect',return_value=conn):
            with self.assertRaises(sqlite3.OperationalError):
                with get_conn():
                    raise sqlite3.OperationalError('trade persistence failed')
        conn.close.assert_called_once()
