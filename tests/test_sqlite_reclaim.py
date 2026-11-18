import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from deploy.sqlite_reclaim import leaf_ranges,reclaim

class ReclaimTests(unittest.TestCase):
    def test_unused_leaf_zeroing_preserves_records_indexes_and_integrity(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'test.sqlite'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE evidence(id INTEGER PRIMARY KEY, quote BLOB)')
            db.executemany('INSERT INTO evidence VALUES(?,?)',[(i,bytes([i%255])*6000) for i in range(120)])
            db.execute('CREATE INDEX evidence_quote ON evidence(quote)')
            db.execute('DELETE FROM evidence WHERE id<80');db.commit()
            before=list(db.iterdump());db.close()
            plan=leaf_ranges(path)
            self.assertGreater(plan['leaf_pages'],0)
            def zero_unused(fd,offset,length):
                os.pwrite(fd,b'\0'*length,offset)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch('deploy.sqlite_reclaim.punch_range',side_effect=zero_unused):
                result=reclaim(path,apply=True,backup_sha256=digest)
            self.assertTrue(result['applied'])
            with sqlite3.connect(path) as db:
                self.assertEqual(before,list(db.iterdump()))
                self.assertEqual(('ok',),db.execute('pragma integrity_check').fetchone())
                db.execute('INSERT INTO evidence VALUES(999,?)',(b'new'*5000,));db.commit()
                self.assertEqual(('ok',),db.execute('pragma integrity_check').fetchone())
            with self.assertRaisesRegex(ValueError,'changed_since_backup'):reclaim(path,apply=True,backup_sha256=digest)

    def test_rejects_wal_and_unverified_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'test.sqlite'
            with sqlite3.connect(path) as db:db.execute('CREATE TABLE test(x)')
            with self.assertRaisesRegex(ValueError,'backup'):reclaim(path,apply=True)
            with sqlite3.connect(path) as db:
                db.execute('pragma journal_mode=wal')
                with self.assertRaises(ValueError):leaf_ranges(path)
