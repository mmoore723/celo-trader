import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from config import runtime_exit_review as runtime
from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
from strategy_health.weekly_exit_audit.source import recorded_version


class RuntimeExitReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rule = REVIEWED_STRATEGIES['CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG']
        self.evidence = json.loads((runtime.ROOT/self.rule.evidence_artifact).read_text())
        self.manifest = json.loads((runtime.ROOT/runtime.MANIFEST).read_text())
        for name in [runtime.MANIFEST, self.rule.evidence_artifact] + [s['path'] for s in self.manifest['runtime_sources']]:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(runtime.ROOT/name, target)
        self.env = patch.dict(os.environ, CELO_RUNTIME_EXIT_REVIEW=runtime.REVISION,
                              CELO_RUNTIME_REVIEW_MODE='offline_test')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(reviewed_strategy_integrity_errors.cache_clear)

    def check(self, evidence=None):
        return runtime.review(self.rule, evidence or self.evidence, root=self.root)

    def save_manifest(self):
        (self.root/runtime.MANIFEST).write_text(json.dumps(self.manifest))

    def test_valid_review_preserves_parent_and_grants_no_profitability(self):
        before = copy.deepcopy(self.evidence)
        result = self.check()
        self.assertFalse(result['profitability_validated'])
        self.assertEqual(runtime.REVISION, result['runtime_revision'])
        self.assertEqual(before, self.evidence)
        old = next(s['sha256'] for s in before['runtime_policy_sources'] if s['path'].endswith('vwap_displacement_exit.py'))
        new = next(s['sha256'] for s in result['runtime_policy_sources'] if s['path'].endswith('vwap_displacement_exit.py'))
        self.assertNotEqual(old, new)

    def test_packaged_review_selected_without_environment_flags(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime.REVISION, self.check()['runtime_revision'])

    def test_production_mode_uses_same_reviewed_code(self):
        with patch.dict(os.environ, CELO_RUNTIME_REVIEW_MODE='production'):
            self.assertEqual(runtime.REVISION, self.check()['runtime_revision'])

    def test_empty_override_cannot_disable_integrity_checks(self):
        with patch.dict(os.environ, CELO_RUNTIME_EXIT_REVIEW=''):
            with self.assertRaises(ValueError):
                self.check()

    def test_test_only_manifest_cannot_be_used_in_release(self):
        self.manifest['status']='test_only'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'invalid_runtime_review'):
            self.check()

    def test_unknown_revision_rejected(self):
        with patch.dict(os.environ, CELO_RUNTIME_EXIT_REVIEW='unknown'):
            with self.assertRaises(ValueError):
                self.check()

    def test_changed_source_fails_closed(self):
        p=self.root/'trading/position_manager/manage.py'
        p.write_text(p.read_text()+'\n# tamper\n')
        with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
            self.check()

    def test_changed_historical_evidence_rejected(self):
        (self.root/self.rule.evidence_artifact).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'parent_mismatch'):
            self.check()

    def test_wrong_strategy_version_rejected(self):
        self.manifest['strategies'][self.rule.strategy_id]['strategy_version']='other'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'parent_mismatch'):
            self.check()

    def test_missing_manifest_rejected(self):
        (self.root/runtime.MANIFEST).unlink()
        with self.assertRaises(OSError):
            self.check()

    def test_profitability_claim_rejected(self):
        self.manifest['profitability_validated']=True
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'invalid_runtime_review'):
            self.check()

    def test_path_escape_rejected(self):
        self.manifest['runtime_sources'][0]['path']='../outside.py'
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.check()

    def test_catalog_keeps_integrity_fail_closed(self):
        with patch.dict(os.environ, CELO_RUNTIME_EXIT_REVIEW='unknown'):
            reviewed_strategy_integrity_errors.cache_clear()
            errors=reviewed_strategy_integrity_errors()
            self.assertIn('runtime_review_invalid', errors[self.rule.strategy_id])

    def test_new_entry_provenance_has_separate_runtime_revision(self):
        meta=runtime.provenance(self.rule)
        self.assertEqual(runtime.REVISION,meta['runtime_revision'])
        self.assertEqual(64,len(meta['runtime_review_sha256']))
        self.assertNotIn('strategy_version',meta)

    def test_historical_and_new_weekly_buckets_stay_separate(self):
        old={'strategy_version':'0.2.0'}
        new={**old,'runtime_revision':runtime.REVISION}
        self.assertEqual('0.2.0',recorded_version(old,{}))
        self.assertEqual('0.2.0+runtime.'+runtime.REVISION,recorded_version(new,old))
        self.assertNotEqual(recorded_version(old,{}),recorded_version(new,old))

    def test_conflicting_runtime_is_not_pooled(self):
        self.assertIsNone(recorded_version({'strategy_version':'0.2.0','runtime_revision':'a'},
                                          {'strategy_version':'0.2.0','runtime_revision':'b'}))

    def test_conflicting_strategy_version_is_not_pooled(self):
        self.assertIsNone(recorded_version({'strategy_version':'0.2.0'}, {'strategy_version':'0.1.0'}))

    def test_missing_strategy_version_is_not_invented(self):
        self.assertIsNone(recorded_version({'runtime_revision':runtime.REVISION}, {}))

    def test_journal_reader_separates_runtime_without_rewriting_trades(self):
        from strategy_health.weekly_exit_audit.source import load
        path=self.root/'journal.db'
        with sqlite3.connect(path) as conn:
            conn.execute('''CREATE TABLE trades(id INTEGER,ticker TEXT,strategy_id TEXT,
                contract_symbol TEXT,broker_account_id TEXT,parent_trade_id INTEGER,status TEXT,
                paper INTEGER,entry_time TEXT,exit_time TEXT,entry_price REAL,contracts INTEGER,
                realized_pnl REAL,strategy_context_json TEXT)''')
            for i, revision in enumerate((None,runtime.REVISION),1):
                context={'strategy_version':'0.2.0','reviewed_exit_minutes':30}
                if revision:
                    context['runtime_revision']=revision
                conn.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (i,'TSLA',self.rule.strategy_id,'TSLA261120C00300000','account',None,'closed',
                     1,'2026-10-30T10:00:00','2026-10-30T10:30:00',2,1,10,json.dumps(context)))
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        buckets=load(path,'paper')
        self.assertEqual({'0.2.0','0.2.0+runtime.'+runtime.REVISION},{k[-1] for k in buckets})
        self.assertTrue(all(len(rows)==1 for rows in buckets.values()))
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
