import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from broker.tradier_chain import TradierChainMixin
from trading.entry.audit_evidence import entry_greeks
from strategy_health.weekly_exit_audit.source import load
from strategy_health.weekly_exit_audit.engine import audit
from tests.test_weekly_exit_audit import trade


class AuditInputCaptureTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,2,15,tzinfo=timezone.utc)
        self.symbol='TSLA260116C00300000'
        self.quote={'symbol':self.symbol,'source_symbol':self.symbol,'quote_source':'tradier',
            'quote_received_at':self.start.isoformat(),
            'greeks':{'updated_at':self.start.isoformat(),'mid_iv':.4,'delta':.5,'gamma':.02}}

    def test_single_quote_requests_and_preserves_greeks(self):
        client=TradierChainMixin();client.api_key='offline'
        client._get=Mock(return_value={'quotes':{'quote':{'symbol':self.symbol,'bid':2,'ask':2.1,
                                                         'greeks':self.quote['greeks']}}})
        with patch('broker.tradier_chain.datetime') as clock:
            clock.now.return_value=self.start
            quote=client.get_option_quote(self.symbol)
        self.assertEqual('true',client._get.call_args.args[1]['greeks'])
        self.assertEqual(self.quote['greeks'],quote['greeks'])
        result=entry_greeks(quote,self.symbol,self.start)
        self.assertEqual((.4,.5,.02),tuple(result[k] for k in ('entry_iv','entry_delta','entry_gamma')))

    def test_missing_values_not_zero(self):
        self.quote['greeks'].pop('gamma')
        self.assertIsNone(entry_greeks(self.quote,self.symbol,self.start)['entry_gamma'])

    def test_wrong_contract_rejected(self):
        self.quote['source_symbol']='OTHER'
        self.assertIsNone(entry_greeks(self.quote,self.symbol,self.start)['entry_iv'])

    def test_unknown_provider_time_preserves_observed_snapshot(self):
        self.quote['greeks'].pop('updated_at')
        data=entry_greeks(self.quote,self.symbol,self.start)
        self.assertEqual(.4,data['entry_iv'])
        self.assertFalse(data['entry_greeks_snapshot']['model_timestamp_verified'])
        self.assertIsNone(data['entry_greeks_snapshot']['model_age_seconds'])

    def test_actual_provider_naive_timestamp_persists_without_timezone_guess(self):
        self.quote['greeks']['updated_at']='2026-01-02 14:00:04'
        data=entry_greeks(self.quote,self.symbol,self.start)
        self.assertEqual('recorded_snapshot_unknown_model_time',data['entry_greeks_snapshot']['status'])
        self.assertEqual('2026-01-02 14:00:04',data['entry_greeks_snapshot']['provider_updated_at'])
        with tempfile.TemporaryDirectory() as directory:
            path=self.fixture(directory)
            trades=next(iter(load(path,'paper').values()))
            self.assertEqual(.4,trades[0]['entry_iv'])
            self.assertFalse(trades[0]['entry_greeks_evidence']['model_timestamp_verified'])

    def test_invalid_receipt_time_still_rejected(self):
        self.quote['quote_received_at']='2026-01-02 15:00:00'
        self.assertIsNone(entry_greeks(self.quote,self.symbol,self.start)['entry_iv'])

    def test_future_provider_time_rejected(self):
        self.quote['greeks']['updated_at']=(self.start+timedelta(seconds=1)).isoformat()
        self.assertIsNone(entry_greeks(self.quote,self.symbol,self.start)['entry_iv'])

    def test_invalid_greeks_rejected(self):
        self.quote['greeks'].update(mid_iv=float('nan'),delta=2,gamma=-1)
        data=entry_greeks(self.quote,self.symbol,self.start)
        self.assertTrue(all(data[k] is None for k in ('entry_iv','entry_delta','entry_gamma')))
        json.dumps(data, allow_nan=False)

    def test_model_age_is_not_fabricated_as_fill_time(self):
        self.quote['greeks']['updated_at']=(self.start-timedelta(minutes=20)).isoformat()
        data=entry_greeks(self.quote,self.symbol,self.start)
        self.assertEqual(1200,data['entry_greeks_snapshot']['model_age_seconds'])

    def test_optional_data_does_not_block_dollar_grid(self):
        t=trade()
        for k in ('entry_iv','entry_delta','entry_gamma','underlying_path'):t[k]=None
        result=audit([t])
        self.assertEqual('COMPLETE',result['status'])
        self.assertEqual(936,len(result['grid']))
        self.assertFalse(result['supplemental_inputs_complete'])
        self.assertEqual(4,len(result['supplemental_coverage_issues']['1']))
        self.assertEqual('KEEP BASELINE',result['recommendation'])

    def test_required_quote_gaps_still_block(self):
        t=trade();t['option_path']=t['option_path'][:1]
        self.assertEqual('INCOMPLETE',audit([t])['status'])

    def fixture(self, directory, candle_account='a', gap=False, future_greeks=False):
        path=Path(directory)/'paper.db'
        context={'strategy_version':'v1','reviewed_exit_minutes':5,
                 **entry_greeks(self.quote,self.symbol,self.start)}
        if future_greeks:
            context['entry_greeks_snapshot']['received_at']=(self.start+timedelta(minutes=1)).isoformat()
        with sqlite3.connect(path) as conn:
            conn.executescript('''CREATE TABLE trades(id INTEGER,ticker TEXT,strategy_id TEXT,
                contract_symbol TEXT,broker_account_id TEXT,parent_trade_id INTEGER,status TEXT,
                paper INTEGER,entry_time TEXT,exit_time TEXT,entry_price REAL,contracts INTEGER,
                realized_pnl REAL,strategy_context_json TEXT);
                CREATE TABLE scanner_candle_observations(broker_account_id TEXT,ticker TEXT,timeframe TEXT,
                bar_time TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,source TEXT,recorded_at TEXT);
                CREATE TABLE option_quote_observations(id INTEGER,trade_id INTEGER,contract_symbol TEXT,
                observed_at TEXT,bid REAL,ask REAL);''')
            conn.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (1,'TSLA','trend',self.symbol,'a',None,'closed',1,self.start.isoformat(),
                 (self.start+timedelta(minutes=5)).isoformat(),2,1,16.7,json.dumps(context)))
            for i in range(5):
                if gap and i==2:continue
                at=self.start+timedelta(minutes=i)
                conn.execute('INSERT INTO scanner_candle_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (candle_account,'TSLA','1Min',at.isoformat(),100,101,99,100,10,'tradier',
                     (at+timedelta(minutes=1)).isoformat()))
            for i,q in enumerate(trade()['option_path']):
                conn.execute('INSERT INTO option_quote_observations VALUES(?,?,?,?,?,?)',
                             (i,1,self.symbol,q['time'],q['bid'],q['ask']))
        return path

    def test_capture_persist_read_and_audit_without_history_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.fixture(d)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            row=next(iter(load(path,'paper').values()))[0]
            self.assertEqual((.4,.5,.02),tuple(row[k] for k in ('entry_iv','entry_delta','entry_gamma')))
            self.assertEqual(5,len(row['underlying_path']))
            self.assertEqual('COMPLETE',audit([row])['status'])
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_candles_never_cross_accounts(self):
        with tempfile.TemporaryDirectory() as d:
            row=next(iter(load(self.fixture(d,candle_account='b'),'paper').values()))[0]
            self.assertIsNone(row['underlying_path'])

    def test_candle_gap_not_filled(self):
        with tempfile.TemporaryDirectory() as d:
            row=next(iter(load(self.fixture(d,gap=True),'paper').values()))[0]
            self.assertIsNone(row['underlying_path'])
            self.assertEqual(1,row['underlying_path_evidence']['missing_bars'])

    def test_post_entry_greeks_never_relabelled_as_entry(self):
        with tempfile.TemporaryDirectory() as d:
            row=next(iter(load(self.fixture(d,future_greeks=True),'paper').values()))[0]
            self.assertIsNone(row['entry_iv'])
