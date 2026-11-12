import json
import sqlite3
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from api.decision_explanation import explain_decision
from api.routes.signals import get_scanner_opportunities
from database.schema import _init_db_at

SCREEN = {'allowed': False, 'reasons': ['premarket_rvol_below_minimum'], 'minimum_rvol': 1.,
          'evidence': {'rvol': .44215, 'premarket_history_sessions': 7,
                       'premarket_window': '04:00-09:30 America/New_York'}}

class DecisionExplanationTests(unittest.TestCase):
    def test_teaches_saved_volume_and_never_uses_current_thresholds(self):
        e = explain_decision({'ticker':'AAPL','direction':'bullish'},
            {'entry_plan':{'underlying_price':355.8}},
            {'premarket_screen':SCREEN,'timeframe_minutes':5},
            'premarket_screen_rejected',None,'saved')
        self.assertIn('44.2%',e['checks'][0]['saw'])
        self.assertIn('100%',e['checks'][0]['required'])
        self.assertIn('not volume at the afternoon signal',e['checks'][0]['meaning'])
        self.assertIn('$355.80',e['setup'])
        self.assertIn('7 earlier sessions',e['where'])

    def test_unknown_failure_is_not_invented(self):
        e=explain_decision({'ticker':'AAPL','direction':'bullish'}, {}, {}, None,None,'saved')
        self.assertEqual([],e['checks']); self.assertIsNone(e['conclusion'])

    def test_saved_rejection_is_read_only_and_cannot_override_other_outcomes(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.db';_init_db_at(path)
            conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row
            for outcome in ['pending','entered','observed_only','blocked']:
                conn.execute('INSERT INTO shadow_candidates (candidate_id,observed_at,ticker,strategy_id,direction,confidence,tier,broker_account_id,final_outcome,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (outcome,'2026-11-12T14:25:00-05:00','AAPL','V2_GAP_FILL_RTH','bullish',.8,'main','paper:test',outcome,json.dumps({'premarket_screen':SCREEN})))
            conn.commit()
            @contextmanager
            def connection(): yield conn
            with patch('database.get_conn',connection),patch('config.get_settings',return_value={'active_broker_account_id':'paper:test'}):
                response=get_scanner_opportunities(date='2026-11-12',ticker=None,strategy=None,outcome=None,feed=None,limit=100)
            entries={r['id']:r for r in response['entries']}
            self.assertEqual('blocked',entries['pending']['outcome'])
            self.assertEqual('premarket_screen_rejected',entries['pending']['reason_code'])
            self.assertIn('missing',entries['pending']['explanation']['source'])
            for outcome in ['entered','observed_only','blocked']:
                self.assertEqual(outcome,entries[outcome]['outcome'])
                self.assertIsNone(entries[outcome]['reason_code'])
            self.assertEqual('pending',conn.execute("SELECT final_outcome FROM shadow_candidates WHERE candidate_id='pending'").fetchone()[0])
            conn.close()

    def test_future_rejection_journal_preserves_exact_candidate_and_screen(self):
        from router_gates.helpers import _journal_dropped
        from types import SimpleNamespace
        sig=SimpleNamespace(strategy_id='V2_GAP_FILL_RTH',direction='bullish',confidence=.8,trigger_bar='14:25',meta={'shadow_candidate_id':'exact','premarket_screen':SCREEN})
        with patch('router_gates.helpers._log_journal') as log:
            _journal_dropped([sig],[],'AAPL','premarket_screen_rejected','Saved check failed')
        self.assertEqual('exact',log.call_args.kwargs['context']['strategy_meta']['shadow_candidate_id'])
        self.assertEqual(SCREEN,log.call_args.kwargs['context']['strategy_meta']['premarket_screen'])
