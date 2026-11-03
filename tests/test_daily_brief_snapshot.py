import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from api import daily_brief


class DailyBriefSnapshotTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(daily_brief, 'trading_tickers', return_value=['SPY'])
        self.allowed = p.start()
        self.addCleanup(p.stop)

    def test_saved_research_tickers_disappear_immediately_without_rebuilding(self):
        with patch.object(daily_brief, '_saved', return_value={
                'date': '2026-11-03', 'prepared_at': '2026-11-03T09:00:00',
                'rows': [{'ticker': 'SPY'}, {'ticker': 'AMD'}, {'ticker': 'NFLX'}]}), \
             patch('database._now_et', return_value=datetime(2026, 11, 3, 10)):
            self.assertEqual(['SPY'], [r['ticker'] for r in daily_brief.read_report()])
            self.allowed.return_value = []
            self.assertEqual([], daily_brief.read_report())

    def test_background_build_persists_across_reads_and_next_day_rebuilds(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(daily_brief, '_path', return_value=Path(folder) / 'brief.json'), \
             patch('database._now_et', return_value=datetime(2026, 10, 12, 9)) as now, \
             patch('config.get_api_keys', return_value={'alpaca_api_key': 'saved'}), \
             patch('api.routes.market.build_premarket_report', return_value=[{'ticker': 'SPY', 'price': 100}]) as build:
            daily_brief.prepare()
            for _ in range(3):
                self.assertEqual('SPY', daily_brief.read_report()[0]['ticker'])
                daily_brief.prepare()
            build.assert_called_once_with('')
            now.return_value = datetime(2026, 10, 13, 8)
            with self.assertRaises(HTTPException):
                daily_brief.read_report()
            daily_brief.prepare()
            self.assertEqual(1, build.call_count)
            now.return_value = datetime(2026, 10, 13, 9)
            daily_brief.prepare()
            self.assertEqual(2, build.call_count)

    def test_missing_report_never_starts_analysis_in_request(self):
        with patch.object(daily_brief, '_saved', return_value={}), \
             patch('api.routes.market.build_premarket_report') as build:
            with self.assertRaises(HTTPException):
                daily_brief.read_report()
            build.assert_not_called()

    def test_failed_empty_report_is_not_frozen_for_day(self):
        with patch.object(daily_brief, '_saved', return_value={}), \
             patch('database._now_et', return_value=datetime(2026, 10, 12, 9)), \
             patch('config.get_api_keys', return_value={'alpaca_api_key': 'saved'}), \
             patch('api.routes.market.build_premarket_report', return_value=[]), \
             patch('config.atomic_files.atomic_write_json') as write:
            daily_brief.prepare()
            write.assert_not_called()
