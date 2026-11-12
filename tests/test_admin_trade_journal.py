import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from api.admin_journal import read_journal, entry_epoch
from api.routes.admin import trade_journal


class AdminJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        with sqlite3.connect(self.root/'users.db') as db:
            db.execute('CREATE TABLE users(id,username)')
            db.executemany('INSERT INTO users VALUES (?,?)',[('a','alice'),('b','bob')])
        for uid, mode, at in [('a','paper','2026-11-11T11:00:00'),('b','live','2026-11-11T17:00:00Z'),
                              ('retired','paper','2026-11-11T10:00:00')]:
            directory=self.root/uid; directory.mkdir(exist_ok=True)
            with sqlite3.connect(directory/f'trades_{mode}.db') as db:
                db.execute('CREATE TABLE trades(id,ticker,option_type,entry_price,exit_price,contracts,entry_time,status,paper,broker_account_id,strategy_context_json,entry_order_id)')
                db.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (1,'QQQ','call',1.0,1.2,2,at,'closed',int(mode=='paper'),'old-account',
                     '{"strategy_version":"v1","private_extra":"do not expose"}','order-one'))

    def test_all_users_modes_accounts_sorted_and_paginated_without_mutation(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*.db')}
        first=read_journal(self.root,limit=1)
        self.assertEqual(3,first['total']); self.assertTrue(first['has_more'])
        self.assertEqual('bob',first['trades'][0]['username'])
        self.assertEqual('live',first['trades'][0]['mode'])
        second=read_journal(self.root,offset=1,limit=1)['trades'][0]
        self.assertEqual('alice',second['username'])
        self.assertEqual('old-account',second['broker_account_id'])
        self.assertEqual('v1',second['strategy_version'])
        self.assertNotEqual(first['trades'][0]['journal_key'],second['journal_key'])
        self.assertNotIn('private_extra',str(second))
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*.db')})
        retained=read_journal(self.root,offset=2,limit=1)['trades'][0]
        self.assertTrue(retained['retained_user'])

    def test_filters_and_no_path_traversal(self):
        self.assertEqual(1,read_journal(self.root,user_id='a',mode='paper')['total'])
        self.assertEqual(0,read_journal(self.root,user_id='../')['total'])
        self.assertEqual(0,read_journal(self.root,ticker="QQQ' OR 1=1 --")['total'])
        self.assertEqual(0,read_journal(self.root,status='open')['total'])
        self.assertEqual(2,read_journal(self.root,mode='paper')['total'])

    def test_error_visible_and_other_users_continue(self):
        (self.root/'a'/'trades_paper.db').write_bytes(b'not a database')
        report=read_journal(self.root)
        self.assertEqual(2,report['total']); self.assertEqual(1,len(report['warnings']))

    def test_admin_required_before_read(self):
        with patch('api.admin_journal.read_journal') as reader:
            with self.assertRaises(HTTPException) as exc:
                trade_journal(SimpleNamespace(state=SimpleNamespace(is_admin=False)))
            self.assertEqual(403,exc.exception.status_code); reader.assert_not_called()

    def test_legacy_eastern_and_aware_clock_match(self):
        self.assertEqual(entry_epoch('2026-11-11T11:00:00'),entry_epoch('2026-11-11T16:00:00Z'))
