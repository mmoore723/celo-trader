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
