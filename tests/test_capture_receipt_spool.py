import json
import unittest
from unittest.mock import patch
from datetime import timedelta
from strategy_health.capture_spool import ReceiptSpool
from tests.test_fast_capture import FastCaptureTests, NOW, SYMBOL

class ReceiptSpoolTests(FastCaptureTests):
    def test_receipt_survives_restart_and_duplicate_commit(self):
        self.add()
        q={'quotes':{'quote':self.quote()}}
        spool=ReceiptSpool(self.root,start=False)
        spool.enqueue([SYMBOL],q,NOW,NOW)
        recovered=ReceiptSpool(self.root,start=False)
        self.assertEqual([],self.r.due(NOW,recovered.next_due))
        self.r.record([SYMBOL],q,NOW,NOW)  # crash after commit, before queue deletion
        self.assertTrue(recovered.drain_one(self.r))
        self.assertEqual(1,self.r.db.execute('select count(*) from observations').fetchone()[0])
        self.assertEqual(1,self.r.db.execute('select count(*) from batches').fetchone()[0])
        self.assertEqual(0,recovered.health()['pending_batches'])

    def test_failed_writer_keeps_original_receipt(self):
        self.add(); spool=ReceiptSpool(self.root,start=False)
        spool.enqueue([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        with patch.object(self.r,'record',side_effect=RuntimeError('database busy')):
            with self.assertRaises(RuntimeError):spool.drain_one(self.r)
        self.assertEqual(1,spool.health()['pending_batches'])
        self.assertTrue(spool.drain_one(self.r))
        self.assertEqual(NOW.isoformat(),self.r.db.execute('select received_at from observations').fetchone()[0])

    def test_pending_batch_does_not_starve_other_contracts(self):
        symbols=['SPY261120C'+str(50000000+i).zfill(8) for i in range(610)]
        for symbol in symbols:self.add(symbol=symbol)
        spool=ReceiptSpool(self.root,start=False)
        first=self.r.due(NOW)
        spool.enqueue(first,{'quotes':{'quote':[self.quote(s) for s in first]}},NOW,NOW)
        self.assertEqual(10,len(self.r.due(NOW+timedelta(seconds=2),spool.next_due)))
        self.assertEqual(600,len(self.r.due(NOW+timedelta(seconds=5),spool.next_due)))

    def test_backlog_is_bounded_and_no_receipt_deleted(self):
        spool=ReceiptSpool(self.root,start=False)
        with patch('pathlib.Path.glob',return_value=iter([None]*1000)):
            with self.assertRaisesRegex(ValueError,'backlog_limit'):
                spool.enqueue([SYMBOL],{},NOW,NOW)

    def test_slow_database_does_not_block_next_receipt(self):
        import threading,time
        entered=threading.Event(); release=threading.Event()
        original=type(self.r).record
        def delayed(registry,*args):
            entered.set(); release.wait(5)
            return original(registry,*args)
        self.add()
        with patch.object(type(self.r),'record',delayed):
            spool=ReceiptSpool(self.root)
            try:
                spool.enqueue([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
                self.assertTrue(entered.wait(2))
                start=time.monotonic();at=NOW+timedelta(seconds=5)
                spool.enqueue([SYMBOL],{'quotes':{'quote':self.quote(now=at)}},at,at)
                self.assertLess(time.monotonic()-start,1)
                self.assertEqual(2,spool.health()['pending_batches'])
            finally:
                release.set();spool.stop.set();spool.thread.join(3)

    def test_storage_error_reports_reason_without_payload(self):
        from strategy_health.capture_spool import error_code
        self.assertEqual('capture_disk_reserve_below_1GB', error_code(ValueError('capture_disk_reserve_below_1GB')))
        self.assertEqual('ValueError', error_code(ValueError('private provider response')))

    def test_backlog_health_uses_original_clock(self):
        spool=ReceiptSpool(self.root,start=False)
        spool.enqueue([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        report=spool.health()
        self.assertEqual(NOW.isoformat(),report['oldest_pending_at'])
        self.assertGreater(report['oldest_pending_seconds'],10)
        self.assertGreater(report['disk_free_bytes'],0)

    def test_disk_reserve_failure_keeps_receipt_then_recovers(self):
        from collections import namedtuple
        usage=namedtuple('usage','total used free')
        self.add();spool=ReceiptSpool(self.root,start=False)
        spool.enqueue([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        original=list(spool.path.glob('*.json'))[0].read_bytes()
        with patch('shutil.disk_usage',return_value=usage(10**10,10**10,100)):
            with self.assertRaisesRegex(ValueError,'capture_disk_reserve_below_1GB'):spool.drain_one(self.r)
        self.assertEqual(original,list(spool.path.glob('*.json'))[0].read_bytes())
        self.assertTrue(spool.drain_one(self.r))
        row=self.r.db.execute('select requested_at,received_at,payload from observations').fetchone()
        self.assertEqual((NOW.isoformat(),NOW.isoformat()),tuple(row)[:2])
        self.assertEqual(self.quote(),json.loads(__import__('strategy_health.quote_storage',fromlist=['decode_text']).decode_text(row['payload'])))

    def test_index_migration_preserves_all_evidence(self):
        from strategy_health.fast_capture import Registry
        identity=self.add()
        self.r.record([SYMBOL],{'quotes':{'quote':self.quote()}},NOW,NOW)
        before={table:[tuple(r) for r in self.r.db.execute('select * from '+table)] for table in ('observations','links','registrations','batches')}
        self.r.db.execute('CREATE INDEX link_registration_receipt ON links(registration,received_at)')
        migrated=Registry(self.root,reclaim_index=True)
        try:
            for table,rows in before.items():self.assertEqual(rows,[tuple(r) for r in migrated.db.execute('select * from '+table)])
            self.assertNotIn('link_registration_receipt',[r[1] for r in migrated.db.execute('pragma index_list(links)')])
            self.assertEqual(NOW.isoformat(),migrated.health(NOW)[__import__('strategy_health.fast_capture',fromlist=['scope_key']).scope_key('paper-a','paper')][0]['last_collection'])
        finally:migrated.db.close()
