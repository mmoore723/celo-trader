import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import pandas as pd
from trading import decision_trace as trace


class DecisionTraceTests(unittest.TestCase):
    def setUp(self):
        trace.flush()
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'exit_decisions'
        self.context={'root':str(self.root),'identity':{'cycle_id':'cycle','mode':'paper',
                      'trade':{'id':1,'broker_account_id':'account-a','ticker':'SPY','strategy_id':'test'}}}
        token=trace._context.set(self.context); self.addCleanup(trace._context.reset,token)
        self.addCleanup(trace.flush)

    def rows(self):
        self.assertTrue(trace.flush())
        with sqlite3.connect(self.root/'decisions.sqlite3') as c:
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM decisions')]

    def test_exact_input_output_and_mutation_snapshots(self):
        state={'peak':1}
        def evaluate(s): s['peak']=2; return True,'stop'
        self.assertEqual((True,'stop'),trace.traced_call('exit',evaluate,state))
        state['peak']=9
        d=self.rows()[0]['snapshot']['data']
        self.assertEqual(1,d['before']['data']['args'][0]['peak'])
        self.assertEqual(2,d['after']['data']['args'][0]['peak'])
        self.assertEqual([True,'stop'],d['result'])

    def test_exception_unchanged_and_logged(self):
        error=ValueError('native error')
        def fail(): raise error
        with self.assertRaises(ValueError) as caught: trace.traced_call('exit',fail)
        self.assertIs(error,caught.exception)
        self.assertEqual('ValueError',self.rows()[0]['snapshot']['data']['error_type'])

    def test_disk_failure_never_changes_exit(self):
        with patch.object(trace,'_write',side_effect=OSError('full')):
            self.assertEqual((True,'stop'),trace.traced_call('exit',lambda:(True,'stop')))
            self.assertTrue(trace.flush())
        self.assertGreater(trace._stats[str(self.root)]['failed'],0)

    def test_full_queue_never_changes_exit(self):
        with patch.object(trace._queue,'put_nowait',side_effect=trace.Full):
            self.assertEqual('hold',trace.traced_call('exit',lambda:'hold'))
        self.assertGreater(trace._stats[str(self.root)]['dropped'],0)

    def test_disabled_does_not_write_or_change_exit(self):
        with patch.dict('os.environ',{'CELO_EXIT_TRACE_DISABLED':'1'}):
            self.assertEqual('hold',trace.traced_call('exit',lambda:'hold'))
        self.assertFalse(self.root.exists())

    def test_snapshot_redacts_secrets_and_preserves_clocks(self):
        result=trace.snapshot({'api_key':'secret','quote_received_at':datetime(2026,11,9,tzinfo=timezone.utc),'bid':1.2})
        self.assertNotIn('api_key',result['data'])
        self.assertEqual('2026-11-09T00:00:00+00:00',result['data']['quote_received_at'])

    def test_frame_immutable_and_limits_explicit(self):
        frame=pd.DataFrame({'close':[1.,2.]})
        result=trace.snapshot(frame); frame.iloc[0,0]=9
        self.assertEqual(1.,result['data']['data']['data'][0][0])
        limited=trace.snapshot(list(range(3000)))
        self.assertFalse(limited['complete']); self.assertIn('sequence_limit',limited['issues'])

    def test_account_mode_and_version_preserved_no_fill_claim(self):
        trace.note('hold',{'policy_version':'v1'})
        trace._context.set({'root':str(self.root),'identity':{'cycle_id':'b','mode':'live','trade':{'id':1,'broker_account_id':'b','ticker':'SPY','strategy_id':'test'}}})
        trace.note('hold',{'policy_version':'v2'})
        rows=self.rows()
        self.assertEqual(['paper','live'],[r['mode'] for r in rows])
        self.assertEqual(['account-a','b'],[r['trade']['broker_account_id'] for r in rows])
        self.assertTrue(all(r['evidence_type']=='native_decision_observation_not_fill' for r in rows))

    def test_duplicate_event_is_idempotent(self):
        event=dict(self.context['identity'],event_id='same',recorded_at='clock',stage='hold',snapshot={})
        trace._write(str(self.root),event); trace._write(str(self.root),event)
        self.assertEqual(1,len(self.rows()))

    def test_cycle_records_start_end_without_altering_call(self):
        calls=[]; state={'positions':{1:{'peak':1}}}
        @trace.position_cycle
        def native(a,b,t,balance):
            calls.append((a,b,t,balance));state['positions'][1]['peak']=3;return 42
        trade={'id':1,'paper':True,'broker_account_id':'a'}
        with patch('config.paths.get_user_data_dir',return_value=Path(self.temp.name)),patch('trading.state.get_user_state',return_value=state):
            self.assertEqual(42,native('a','b',trade,100))
        self.assertEqual([('a','b',trade,100)],calls)
        rows=self.rows();self.assertEqual(['cycle_start','cycle_end'],[r['stage'] for r in rows])
        self.assertEqual([1,3],[r['snapshot']['data']['peak'] for r in rows])

    def test_oversize_event_explicitly_incomplete(self):
        trace.note('large',['x'*100000]*10)
        self.assertEqual(['event_size_limit'],self.rows()[0]['snapshot']['issues'])

    def test_exit_request_and_partial_response_preserve_arguments_and_identity(self):
        from unittest.mock import Mock
        response={'id':'order-1','filled_qty':'1','status':'partially_filled'}
        broker=Mock(return_value=response)
        order=dict(symbol='contract',qty=2,side='sell',order_type='limit',limit_price=1.5,
                   position_intent='sell_to_close',order_context={'exit_reason':'stage1'})
        self.assertIs(response,trace.exit_order(broker,{'contracts':5},**order))
        broker.assert_called_once_with(**order)
        rows=self.rows();request,reply=[r['snapshot']['data'] for r in rows]
        self.assertEqual(5,request['remaining_contracts'])
        self.assertEqual(order,request['order'])
        self.assertEqual(request['action_id'],reply['action_id'])
        self.assertEqual(response,reply['response'])

    def test_exit_exception_and_logging_failure_do_not_change_broker_behavior(self):
        from unittest.mock import Mock
        error=TimeoutError('unknown execution outcome')
        broker=Mock(side_effect=error)
        with patch.object(trace,'_write',side_effect=OSError('disk')):
            with self.assertRaises(TimeoutError) as caught:
                trace.exit_order(broker,{'contracts':2},qty=2)
            self.assertIs(error,caught.exception)
            broker.assert_called_once_with(qty=2)
            self.assertTrue(trace.flush())

    def test_exit_no_fill_and_retries_are_not_labeled_filled(self):
        for _ in range(2): self.assertIsNone(trace.exit_order(lambda **kw:None,{'contracts':2},qty=1))
        rows=self.rows()
        self.assertNotEqual(rows[0]['snapshot']['data']['action_id'],rows[2]['snapshot']['data']['action_id'])
        self.assertIsNone(rows[1]['snapshot']['data']['response'])

    def test_exit_outside_manager_has_scoped_context_and_restores_it(self):
        token=trace._context.set(None)
        try:
            trade={'id':12,'contracts':1,'paper':True,'broker_account_id':'a'}
            with patch('config.paths.get_user_data_dir',return_value=Path(self.temp.name)):
                self.assertEqual(7,trace.exit_order(lambda **kw:7,trade,qty=1))
            self.assertIsNone(trace._context.get())
            self.assertEqual(12,self.rows()[0]['trade']['id'])
        finally: trace._context.reset(token)


if __name__=='__main__': unittest.main()
