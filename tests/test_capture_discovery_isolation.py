"""Capture-only regressions. All quotes and databases are local fixtures."""
import json
import sqlite3
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from tests import test_fast_capture as fixtures
from tests.test_fast_capture import NOW, SYMBOL
from strategy_health.fast_capture import DiscoveryTask, discover
from broker.tradier_chain import TradierChainMixin


class CaptureDiscoveryIsolationTests(unittest.TestCase):
    setUp=fixtures.FastCaptureTests.setUp
    def source(self):
        path=self.root/'source.db'
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE trades(id,ticker,strategy_id,contract_symbol,
                entry_time,strategy_context_json,broker_account_id,paper,status);
                CREATE TABLE shadow_candidates(candidate_id);
                CREATE TABLE candidate_option_quote_observations(candidate_id);''')
            db.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)',
                (1,'SPY','strategy',SYMBOL,NOW.isoformat(),json.dumps({'strategy_version':'v1'}),
                 'a',1,'open'))
        return path

    def calendar(self):
        return [(NOW,NOW+timedelta(hours=6)),(NOW+timedelta(days=1),NOW+timedelta(days=1,hours=6))]

    def test_broker_registration_survives_broken_research_source(self):
        result=discover(self.source(),'a','paper',self.r,self.calendar(),NOW)
        self.assertEqual(1,result['registered'])
        self.assertEqual('research_selection',result['errors'][0]['source'])
        self.assertEqual('SQLITE_ERROR',result['errors'][0]['code'])
        self.assertEqual([SYMBOL],self.r.due(NOW))

    def test_native_lane_never_reads_research_and_is_independent(self):
        path=self.source(); started=threading.Event(); release=threading.Event()
        research=DiscoveryTask(); native=DiscoveryTask(broker_only=True)
        def delayed(*args,**kwargs):
            if not kwargs.get('broker_only'):
                started.set(); release.wait(5)
                return {'registered':0,'blocked':{}}
            return discover(*args,**kwargs)
        try:
            with patch('strategy_health.fast_capture.discover',side_effect=delayed):
                research.submit(self.root,path,'a','paper',self.calendar(),NOW)
                self.assertTrue(started.wait(2))
                native.submit(self.root,path,'a','paper',self.calendar(),NOW)
                native.future.result(timeout=3)
                result=native.take()['result']
                self.assertEqual(1,result['registered'])
                self.assertEqual([],result['errors'])
                self.assertIsNone(research.take())
                self.assertEqual([SYMBOL],self.r.due(NOW))
        finally:
            release.set(); research.close(); native.close()

    def test_failed_registration_is_retried_without_duplicate_observations(self):
        path=self.source()
        failure=sqlite3.OperationalError('database is locked')
        failure.sqlite_errorname='SQLITE_BUSY'
        with patch.object(self.r,'register',side_effect=failure):
            result=discover(path,'a','paper',self.r,self.calendar(),NOW,broker_only=True)
        self.assertEqual(0,result['registered'])
        self.assertEqual('register',result['errors'][0]['stage'])
        self.assertEqual('SQLITE_BUSY',result['errors'][0]['code'])
        for _ in range(2):
            result=discover(path,'a','paper',self.r,self.calendar(),NOW,broker_only=True)
            self.assertEqual(1,result['registered'])
        self.assertEqual(1,self.r.db.execute('SELECT count(*) FROM registrations').fetchone()[0])
        self.assertEqual(0,self.r.db.execute('SELECT count(*) FROM observations').fetchone()[0])

    def test_old_timeout_reproduces_busy_and_new_background_wait_recovers(self):
        path=self.source()
        # A quote-persistence transaction lasting longer than 200ms reproduced
        # the old failure. This is a controlled reproduction, not a claim that
        # the old logs recorded SQLITE_BUSY (they did not record the code).
        self.r.db.execute('BEGIN IMMEDIATE')
        old_result=[]
        # Use an actual write against a known table, avoiding fixture-schema assumptions.
        def old_write():
            with sqlite3.connect(self.root/'fast_capture.sqlite3',timeout=.2) as db:
                try: db.execute("UPDATE polling SET attempted_at=attempted_at")
                except sqlite3.Error as exc: old_result.append(exc.sqlite_errorname)
        thread=threading.Thread(target=old_write); thread.start(); thread.join(2)
        self.r.db.rollback()
        self.assertEqual(['SQLITE_BUSY'],old_result)
        task=DiscoveryTask(broker_only=True)
        try:
            self.r.db.execute('BEGIN IMMEDIATE')
            task.submit(self.root,path,'a','paper',self.calendar(),NOW)
            time.sleep(.3)
            self.r.db.rollback()
            task.future.result(timeout=3)
            self.assertEqual(1,task.take()['result']['registered'])
        finally:
            self.r.db.rollback(); task.close()


class NativeQuoteSizeTests(unittest.TestCase):
    def test_sizes_are_requested_preserved_and_missing_stays_unknown(self):
        client=TradierChainMixin(); client.api_key='fixture'
        quote=dict(symbol=SYMBOL,bid=1,ask=1.1,bidsize=7,asksize=9,bid_date=1234,ask_date=1235)
        client._get=Mock(return_value={'quotes':{'quote':quote}})
        result=client.get_option_quote(SYMBOL)
        self.assertEqual('true',client._get.call_args.args[1]['includeLotSize'])
        self.assertEqual((7,9,1234,1235),tuple(result[k] for k in ('bidsize','asksize','bid_date','ask_date')))
        del quote['bidsize']; del quote['asksize']
        result=client.get_option_quote(SYMBOL)
        self.assertIsNone(result['bidsize']); self.assertIsNone(result['asksize'])
