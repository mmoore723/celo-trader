from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

import pandas as pd
import strategy_router.route as router
from trading.diagnostics import native_coverage as coverage
from trading.diagnostics.native_coverage_report import read_record, summarize
from trading.diagnostics.strategy_scan import scan_message, log_strategy_scan

SID = 'V2_SPY_TREND_CONT'


def signal(sid=SID):
    return SimpleNamespace(strategy_id=sid,meta={},direction='bullish',confidence=.8,
                           rvol=1.5,trigger_bar=pd.Timestamp('2026-09-14T10:00:00'))


class NativeCoverageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder/'native_decision_coverage.sqlite3'
        self.frame = pd.DataFrame({'time':pd.date_range('2026-09-14T10:00',periods=2,freq='min'),
                                   'close':[100.,101.]})
        self.settings = dict(active_broker_account_id='private-account',paper_trading=True)
        for target,value in [('get_current_user_id','test-user'),('get_user_data_dir',self.folder)]:
            p = patch.object(coverage,target,return_value=value)
            p.start(); self.addCleanup(p.stop)

    def begin(self,ticker='SPY',enabled=None,statuses=None):
        return coverage.begin(ticker,{SID} if enabled is None else enabled,statuses or {},self.frame,
            settings=self.settings,now=datetime(2026,9,14,10,2))

    def route(self,collector,fn=None,**kwargs):
        with patch.object(router,'ACTIVE_STRATEGIES',[(SID,fn or (lambda *a,**k:signal()))]), \
             patch.object(router,'_authorized_for_order',return_value=True), \
             patch.object(router,'check_kill_lock',return_value=(False,'')), \
             patch.object(router,'_emit_signal_annotation'), \
             patch.object(router,'compute_adx',return_value=30.):
            return router.route_signals(self.frame,'SPY',enabled_strategies={SID},prepared_today=self.frame,
                preserve_reviewed_paid_rules=True,evaluation_observer=collector.observe,**kwargs)

    def rows(self):
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute('SELECT payload,payload_sha256 FROM coverage').fetchall()
        finally:
            conn.close()

    def test_signal_is_identical_and_record_correlates_without_private_account(self):
        collector = self.begin(); original = signal()
        returned = self.route(collector,lambda *a,**k:original)
        self.assertIs(original,returned[0])
        collector.finish(returned)
        packed,digest=self.rows()[0]
        account=hashlib.sha256(b'private-account').hexdigest()
        record=read_record(packed,digest,account,True)
        self.assertNotIn('private-account',zlib.decompress(packed).decode())
        self.assertEqual('signal_returned',record['strategies'][SID]['evaluation'])
        self.assertEqual('returned',record['strategies'][SID]['routing'])
        self.assertFalse(record['complete_replay_inputs'])
        self.assertEqual(0o600,self.path.stat().st_mode&0o777)

    def test_all_six_native_strategies_and_seven_pairs_are_in_scope(self):
        seen=set()
        for ticker in ('SPY','TSLA','AMZN'):
            collector=self.begin(ticker,set(coverage.PAIRS))
            seen.update((sid,ticker) for sid in collector.payload['strategies'])
        self.assertEqual(7,len(seen))
        self.assertEqual(6,len({sid for sid,_ in seen}))
        self.assertIsNone(self.begin('META',set(coverage.PAIRS)))

    def test_disabled_research_unknown_account_and_unknown_mode_do_not_record(self):
        self.assertIsNone(self.begin(enabled=set()))
        self.assertIsNone(self.begin(enabled={'EMA_PULLBACK'}))
        with patch.object(coverage,'get_current_user_id',return_value='system'):
            self.assertIsNone(self.begin())
        self.settings.pop('active_broker_account_id')
        self.assertIsNone(self.begin())
        self.settings['active_broker_account_id']='private-account'
        self.settings.pop('paper_trading')
        self.assertIsNone(self.begin())
        self.assertFalse(self.path.exists())

    def test_evaluator_none_is_not_invented_as_missing_option(self):
        collector=self.begin()
        self.assertEqual([],self.route(collector,lambda *a,**k:None))
        self.assertEqual('no_signal_returned',collector.payload['strategies'][SID]['evaluation'])
        self.assertEqual('no_order_signal',collector.payload['strategies'][SID]['routing'])

    def test_evaluator_error_is_not_narrated_as_no_setup(self):
        def broken(*a,**k): raise ValueError('private error details')
        collector=self.begin()
        self.assertEqual([],self.route(collector,broken))
        self.assertEqual('evaluation_error',collector.payload['strategies'][SID]['evaluation'])
        message=scan_message('SPY',{SID},{},[],coverage=collector.payload)
        self.assertIn('Evaluation failed',message)
        self.assertNotIn('private error details',json.dumps(collector.payload))

    def test_injected_error_and_status_are_preserved(self):
        collector=self.begin('TSLA',{'V2_ORB_PULLBACK','V2_TSLA_TWO_LEG_TREND_PULLBACK'},
            {'V2_ORB_PULLBACK':'armed_waiting_for_first_retouch',
             'V2_TSLA_TWO_LEG_TREND_PULLBACK':'data_check_failed'})
        self.assertEqual('armed_waiting_for_first_retouch',collector.payload['strategies']['V2_ORB_PULLBACK']['evaluation'])
        message=scan_message('TSLA',{'V2_TSLA_TWO_LEG_TREND_PULLBACK'},
                            {'V2_TSLA_TWO_LEG_TREND_PULLBACK':'data_check_failed'},[])
        self.assertIn('Evaluation failed',message)

    def test_quiet_research_does_not_emit_execution_observations(self):
        collector=self.begin(); self.route(collector,quiet=True)
        self.assertEqual([],collector.payload['strategies'][SID]['events'])

    def test_callback_failure_cannot_suppress_signal(self):
        collector=self.begin()
        with patch.object(collector,'observe',side_effect=RuntimeError('unavailable')):
            self.assertEqual(1,len(self.route(collector)))

    def test_empty_input_and_kill_lock_do_not_claim_evaluation(self):
        collector=self.begin()
        with patch.object(router,'check_kill_lock',return_value=(True,'locked')):
            self.assertEqual([],router.route_signals(self.frame,'SPY',enabled_strategies={SID},
                evaluation_observer=collector.observe))
        self.assertEqual('not_recorded',collector.payload['strategies'][SID]['evaluation'])
        self.assertEqual('kill_lock',collector.payload['strategies'][SID]['routing'])
        self.assertIn('kill_lock',scan_message('SPY',{SID},{},[],coverage=collector.payload))
        collector=self.begin()
        router.route_signals(pd.DataFrame(),'SPY',enabled_strategies={SID},evaluation_observer=collector.observe)
        self.assertEqual('insufficient_input',collector.payload['strategies'][SID]['routing'])

    def test_cap_preserves_old_records_and_has_no_wal(self):
        self.begin().finish([]); original=self.rows()
        with patch.object(coverage,'MAX_DATABASE_BYTES',self.path.stat().st_size):
            self.begin().finish([])
        self.assertEqual(original,self.rows())
        self.assertFalse(Path(str(self.path)+'-wal').exists())

    def test_full_disk_locked_database_and_payload_budget_are_nonfatal(self):
        with patch.object(coverage,'append',side_effect=OSError('disk full')):
            self.begin().finish([signal()])
        self.begin().finish([])
        conn=sqlite3.connect(self.path)
        try:
            conn.execute('BEGIN EXCLUSIVE')
            self.begin().finish([signal()])
        finally:
            conn.rollback(); conn.close()
        self.assertEqual(1,len(self.rows()))
        with patch.object(coverage,'MAX_PAYLOAD_BYTES',1):
            self.begin().finish([signal()])
        self.assertEqual(1,len(self.rows()))

    def test_no_symlink_target_write(self):
        target=self.folder/'private'; target.write_text('untouched')
        self.path.symlink_to(target)
        self.begin().finish([])
        self.assertEqual('untouched',target.read_text())

    def test_readonly_summary_scopes_account_and_mode_and_does_not_claim_complete(self):
        self.begin().finish([])
        self.settings['paper_trading']=False; self.begin().finish([])
        self.settings['active_broker_account_id']='different'; self.begin().finish([])
        before=self.path.read_bytes()
        report=summarize(self.path,hashlib.sha256(b'private-account').hexdigest(),True)
        self.assertEqual(1,report['recorded_passes'])
        self.assertEqual(1,report['by_pair'][SID+'|SPY']['evaluation']['not_recorded'])
        self.assertFalse(report['full_session_coverage'])
        self.assertFalse(report['option_fills_verified'])
        self.assertEqual(before,self.path.read_bytes())

    def test_tamper_and_compression_bomb_rejected(self):
        self.begin().finish([]); packed,digest=self.rows()[0]
        account=hashlib.sha256(b'private-account').hexdigest()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            read_record(packed,'wrong',account,True)
        with self.assertRaisesRegex(ValueError,'scope mismatch'):
            read_record(packed,digest,account,False)
        with self.assertRaisesRegex(ValueError,'compressed'):
            read_record(zlib.compress(b'x'*(coverage.MAX_PAYLOAD_BYTES+1)),'unused',account,True)

    def test_narration_storage_error_does_not_abort_trading(self):
        with patch('trading.diagnostics.strategy_scan.log_event',side_effect=OSError('disk full')):
            log_strategy_scan({},'SPY',{SID},{},[],datetime(2026,9,14,10))


if __name__=='__main__':
    unittest.main()
