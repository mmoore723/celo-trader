from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
import zlib
from api.routes.archived_chart import archived_chart, ET

class ArchivedChartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = str(Path(self.tmp.name)/'history.sqlite3')
        self.db = sqlite3.connect(self.path)
        self.db.executescript('CREATE TABLE bars(day,ticker,minute,first_received_at,response_id); CREATE TABLE responses(id PRIMARY KEY,payload);')
        self.now = datetime(2026,11,17,16,0,tzinfo=ET)
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
        archived_chart.cache_clear()
    def add(self, day, minutes, identity='a', ticker='SPY', late=False):
        start = datetime.fromisoformat(day+'T04:00:00').replace(tzinfo=ET)
        rows=[]
        for m in minutes:
            stamp=start+timedelta(minutes=m)
            rows.append(dict(time=stamp.isoformat(),open=10,high=12,low=9,close=11,volume=100))
            received=stamp+timedelta(minutes=10 if late else 1)
            self.db.execute('INSERT INTO bars VALUES(?,?,?,?,?)',(day,ticker,stamp.isoformat(),received.isoformat(),identity))
        self.db.execute('INSERT INTO responses VALUES(?,?)',(identity,zlib.compress(json.dumps({'series':{'data':rows}}).encode())))
        self.db.commit()
    def read(self, tf='1Min', path=None):
        return archived_chart(path or self.path,'SPY',tf,'5D',int(self.now.timestamp()//60))
    def test_multiple_days_are_not_capped_at_2000_and_no_writes(self):
        for i,day in enumerate(['2026-11-13','2026-11-16','2026-11-17']): self.add(day,range(720),str(i))
        before=Path(self.path).read_bytes()
        data=self.read()
        self.assertEqual(2160,len(data['bars']))
        self.assertEqual(2,len(data['missing_dates']))
        self.assertEqual([],data['gaps'])
        self.assertEqual(before,Path(self.path).read_bytes())
    def test_missing_minutes_and_partial_aggregation_are_explicit(self):
        self.add('2026-11-17',[0,1,3,4,5,6,7,8,9],late=True)
        data=self.read('5Min')
        self.assertEqual(1,len(data['bars']))
        self.assertEqual('2026-11-17T04:05:00',data['bars'][0]['time'])
        self.assertEqual(1,data['partial_buckets_omitted'])
        self.assertEqual(9,data['recovered_minutes'])
        self.assertEqual(711,sum(g['minutes'] for g in data['gaps']))
        self.assertAlmostEqual(32/3,data['bars'][0]['vwap'])
    def test_old_responses_fill_only_recorded_minutes(self):
        self.add('2026-11-17',[0,1],identity='old')
        self.add('2026-11-17',[2],identity='new')
        self.assertEqual(3,len(self.read()['bars']))
    def test_forming_candle_is_excluded(self):
        self.add('2026-11-17',[0,1,2,3])
        self.now=self.now.replace(hour=4,minute=3)
        self.assertEqual(3,len(self.read()['bars']))
    def test_missing_user_archive_does_not_fallback_or_create_files(self):
        self.add('2026-11-17',[0])
        missing=str(Path(self.tmp.name)/'another-user'/'history.sqlite3')
        self.assertEqual([],self.read(path=missing)['bars'])
        self.assertFalse(Path(missing).parent.exists())
    def test_ticker_isolation(self):
        self.add('2026-11-17',[0],ticker='QQQ')
        self.assertEqual([],self.read()['bars'])
