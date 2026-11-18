import json
import sqlite3
import unittest
import zlib
from strategy_health.quote_storage import encode_text,decode_text,migrate_batch,MAGIC,MAX_BYTES

class QuoteStorageTests(unittest.TestCase):
    def test_exact_mixed_roundtrip(self):
        for text in ['{}', json.dumps({'symbol':'QQQ','values':['café']*200},ensure_ascii=False)]:
            self.assertEqual(decode_text(encode_text(text)),text)
        self.assertIsInstance(encode_text('{"large":"'+'a'*1000+'"}'),bytes)

    def test_corruption_and_bomb_rejected(self):
        packed=encode_text('x'*1000)
        with self.assertRaises(ValueError): decode_text(packed[:-3])
        with self.assertRaises(ValueError): decode_text(MAGIC+b'0'*32+zlib.compress(b'x'*(MAX_BYTES+1)))
        with self.assertRaises(ValueError): decode_text(MAGIC+b'0'*32+zlib.compress(b'x'))

    def test_resumable_preserves_keys_times_and_json(self):
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE observations(symbol,received_at,payload)')
        values=[('QQQ',str(i),json.dumps({'bid':i,'context':'x'*1000})) for i in range(5)]
        db.executemany('INSERT INTO observations VALUES(?,?,?)',values);db.commit()
        self.assertEqual(migrate_batch(db,2)['compressed'],2)
        self.assertEqual(migrate_batch(db,2)['compressed'],2)
        self.assertEqual(migrate_batch(db,2)['compressed'],1)
        self.assertEqual(migrate_batch(db,2)['scanned'],0)
        self.assertEqual([(s,t,decode_text(p)) for s,t,p in db.execute('SELECT * FROM observations')],values)
        db.execute('DELETE FROM quote_compression_progress');db.commit()
        self.assertEqual(migrate_batch(db,10)['compressed'],0)
