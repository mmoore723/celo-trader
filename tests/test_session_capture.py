from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zlib
import json

from strategy_health.session_capture import Archive, Feed, ET, bar_stamp, quote_validation, session_window, summary


DAY='2026-11-06'
NOW=datetime(2026,11,6,4,3,tzinfo=ET)
WINDOW=(NOW.replace(minute=0),NOW.replace(hour=20,minute=0))


class SessionCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive=Archive(self.tmp.name)
        self.addCleanup(self.archive.db.close)
        self.archive.enqueue(DAY,['SPY','NFLX'])

    def task(self,kind='bars',ticker='SPY',expiration=''):
        return self.archive.db.execute('SELECT * FROM tasks WHERE day=? AND kind=? AND ticker=? AND expiration=?',
                                       (DAY,kind,ticker,expiration)).fetchone()

    def accept(self,kind,payload,expiration=''):
        self.archive.accept(self.task(kind,expiration=expiration),{},NOW,NOW+timedelta(seconds=1),payload,WINDOW)

    def test_calendar_holidays_and_capture_target_not_broker_hours(self):
        payload={'calendar':{'days':{'day':[{'date':DAY,'status':'open','premarket':{'start':'04:00'},'postmarket':{'end':'17:00'}}]}}}
        start,end=session_window(payload,DAY)
        self.assertEqual(20,end.hour)
        self.assertEqual(4,start.hour)
        self.assertEqual(-18000,start.utcoffset().total_seconds())
        self.assertIsNone(session_window({'calendar':{'days':{'day':{'date':DAY,'status':'closed'}}}},DAY))
        with self.assertRaises(ValueError): session_window(payload,'2026-11-07')

    def test_completed_bars_only_and_missing_minutes_explicit(self):
        rows=[dict(time=f'{DAY} 04:0{m}:00',open=1,high=2,low=1,close=2,volume=10) for m in (0,2,3)]
        self.accept('bars',{'series':{'data':rows}})
        out=summary(self.archive,DAY,['SPY','NFLX'],WINDOW,NOW)
        spy,nflx=out['tickers']
        self.assertEqual(2,spy['captured_minutes'])
        self.assertEqual([NOW.replace(minute=1).isoformat()],spy['missing_minutes'])
        self.assertEqual(0,nflx['captured_minutes'])
        self.assertEqual(3,len(nflx['missing_minutes']))

    def test_restart_no_duplicate_bars_and_preserved_receipt(self):
        data={'series':{'data':[dict(time=f'{DAY} 04:00:00',open=1,high=2,low=1,close=2,volume=10)]}}
        self.accept('bars',data)
        self.accept('bars',data)
        reopened=Archive(self.tmp.name)
        try:
            self.assertEqual(1,reopened.db.execute('SELECT count(*) FROM bars').fetchone()[0])
            row=reopened.db.execute('SELECT * FROM responses').fetchone()
            self.assertEqual('provider_history_received_later',row['provenance'])
            self.assertEqual(data,json.loads(zlib.decompress(row['payload'])))
        finally: reopened.db.close()

    def test_discovery_no_premium_dte_spread_or_strike_filter(self):
        self.accept('expirations',{'expirations':{'date':['2026-11-06','2029-01-19']}})
        quote=dict(symbol='SPY291219C00100000',bid=0,ask=20000,strike=100,
                   bid_date=0,ask_date=0,greeks={'mid_iv':1,'updated_at':'old'})
        self.accept('chain',{'options':{'option':quote}},expiration='2029-01-19')
        out=summary(self.archive,DAY,['SPY'],WINDOW,NOW)['tickers'][0]
        self.assertEqual(2,out['listed_expirations'])
        self.assertEqual(1,out['contracts_discovered'])
        self.assertEqual(0,out['contracts_with_fresh_snapshot'])
        self.assertEqual(['2026-11-06'],out['pending_expirations'])

    def test_invalid_response_preserved_and_task_not_marked_successful(self):
        with self.assertRaises(ValueError): self.accept('bars',{'series':{'data':[]}})
        self.assertEqual(1,self.archive.db.execute('SELECT count(*) FROM responses').fetchone()[0])
        self.assertIsNone(self.task()['last_ok'])
        self.archive.fail(self.task(),'no_candles_returned',NOW)
        self.assertEqual('no_candles_returned',self.task()['error'])

    def test_stale_quote_never_uses_receipt_as_source_time(self):
        raw=dict(bid=1,ask=2,bid_date=NOW.timestamp()*1000,ask_date=NOW.timestamp()*1000)
        self.assertEqual('fresh',quote_validation(raw,NOW))
        self.assertEqual('stale_or_future_quote',quote_validation(raw,NOW+timedelta(seconds=11)))
        del raw['bid_date']
        self.assertEqual('missing_quote_or_source_time',quote_validation(raw,NOW))

    def test_timestamp_disagreement_rejected(self):
        with self.assertRaises(ValueError): bar_stamp(dict(time=DAY+' 04:00:00',timestamp=0))

    def test_allowlisted_feed_no_fallback_or_orders(self):
        feed=Feed('test')
        with self.assertRaises(ValueError): feed.get('accounts/orders')
        response=Mock(status_code=200,headers={},json=lambda: {})
        with patch.object(feed.session,'get',return_value=response) as get:
            feed.get('quotes',{'symbols':'SPY'})
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertTrue(get.call_args.args[0].startswith('https://api.tradier.com/'))
            with self.assertRaisesRegex(ValueError,'budget_wait'): feed.get('quotes')

    def test_bulk_quote_post_is_market_data_only_and_preserves_fields(self):
        feed=Feed('test')
        response=Mock(status_code=200,headers={},json=lambda:{'quotes':{'quote':[]}})
        with patch.object(feed.session,'post',return_value=response) as post:
            feed.quotes(['SPY261120C00600000']*600)
            self.assertEqual('https://api.tradier.com/v1/markets/quotes',post.call_args.args[0])
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            self.assertEqual('true',post.call_args.kwargs['data']['greeks'])
            self.assertEqual('true',post.call_args.kwargs['data']['includeLotSize'])
        for endpoint in ('accounts/orders','calendar','options/chains'):
            with self.assertRaises(ValueError): Feed('test').get(endpoint,quote_body=True)
        for symbols in ([],['SPY']*601,['SPY,QQQ'],[''],None):
            with self.assertRaises(ValueError): Feed('test').quotes(symbols)

    def test_bulk_quotes_share_quota_and_backoff(self):
        import time
        for status in (400,429):
            feed=Feed('test')
            with patch.object(feed.session,'post',return_value=Mock(status_code=status,headers={})):
                with self.assertRaisesRegex(ValueError,'provider_http'): feed.quotes(['SPY'])
                with self.assertRaisesRegex(ValueError,'budget_wait'): feed.get('calendar')
                self.assertGreater(feed.next_request-time.monotonic(),59)
        feed=Feed('test')
        with patch.object(feed.session,'post',return_value=Mock(status_code=200,headers={'X-Ratelimit-Available':'39'},json=lambda:{})):
            feed.quotes(['SPY'])
            self.assertGreater(feed.next_request-time.monotonic(),59)

    def test_400_and_429_back_off_and_leave_trading_reserve(self):
        for status in (400,429):
            feed=Feed('test')
            with patch.object(feed.session,'get',return_value=Mock(status_code=status,headers={})):
                with self.assertRaisesRegex(ValueError,'provider_http'): feed.get('quotes')
                with self.assertRaisesRegex(ValueError,'budget_wait'): feed.get('quotes')
        feed=Feed('test')
        with patch.object(feed.session,'get',return_value=Mock(status_code=200,headers={'X-Ratelimit-Available':'39'},json=lambda:{})):
            feed.get('quotes')
            import time
            self.assertGreater(feed.next_request-time.monotonic(),59)

    def test_empty_universe_not_silently_expanded(self):
        out=summary(self.archive,DAY,[],WINDOW,NOW)
        self.assertEqual([],out['tickers'])

    def test_closed_session_never_claims_one_hundred_percent(self):
        out=summary(self.archive,DAY,['SPY'],None,NOW)
        self.assertIsNone(out['tickers'][0]['coverage_pct'])
        self.assertEqual('outside_session',out['status'])

    def test_saved_api_is_read_only_and_user_scoped(self):
        from api.routes.session_capture import coverage, contracts
        root=Path(self.tmp.name)
        report=dict(heartbeat_at=datetime.now(timezone.utc).isoformat(),status='outside_session',tickers=[])
        # Test fixture writes, not an application runtime mutation.
        (root/'session_capture_health.json').write_text(json.dumps(report))
        with patch('api.routes.session_capture.get_user_data_dir',return_value=root):
            self.assertFalse(coverage()['worker_stale'])
            self.assertEqual({'rows':[],'has_more':False},contracts('SPY',DAY,1))
        other=root/'other_user'
        with patch('api.routes.session_capture.get_user_data_dir',return_value=other):
            self.assertEqual('not_verified',coverage()['status'])
            self.assertFalse(other.exists())

    def test_session_resume_missing_records_not_fabricated(self):
        self.archive.fail(self.task(),'provider_http_429',NOW)
        reopened=Archive(self.tmp.name)
        try:
            task=reopened.db.execute("SELECT * FROM tasks WHERE kind='bars' AND ticker='SPY'").fetchone()
            self.assertEqual('provider_http_429',task['error'])
            self.assertEqual(1,task['failures'])
            self.assertEqual(0,reopened.db.execute('SELECT count(*) FROM bars').fetchone()[0])
        finally: reopened.db.close()

    def test_endpoint_has_no_broker_or_worker_imports(self):
        source=Path('api/routes/session_capture.py').read_text()
        self.assertNotIn('import requests',source)
        self.assertNotIn('session_capture import',source)
        self.assertNotIn('@router.post',source)
        source=Path('strategy_health/session_capture.py').read_text()
        self.assertNotIn('submit_order',source)
        self.assertNotIn('save_settings',source)


if __name__=='__main__': unittest.main()
