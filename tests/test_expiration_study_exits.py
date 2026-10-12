from copy import deepcopy
from contextlib import contextmanager
from datetime import timedelta
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from strategy_health import expiration_study_exits as exits
from database import expiration_study as storage
from trading.expiration_study_selection import PROFILE
from strategy_health import impulse_exit, context_orb_exit, squeeze_exit
from strategy_health.impulse_exit import et
from tests.test_impulse_exit_measurement import candles
from tests.test_context_orb_exit_measurement import meta as orb_meta
from tests.test_squeeze_exit_measurement import meta as squeeze_meta


def selection(entry='2026-09-10T10:05:03'):
    return dict(profile_version=PROFILE, status='selected', reason='selected',
                setup_at='2026-09-10T10:05:01', contract=dict(
                    symbol='XYZ', ask=2.0, bid=1.9, entry_quote_at=entry))


def initial(sid=impulse_exit.STRATEGY_ID, **changes):
    meta=dict(strategy_version='test.1', underlying_stop=98, underlying_target=104,
              authored_exit_protocol=exits.PROTOCOL_BY_STRATEGY[sid])
    if sid in context_orb_exit.PREMIUM_PROTOCOLS:
        meta.update(context_orb_exit.metadata(sid), or_midpoint=98)
    if sid == squeeze_exit.STRATEGY_ID:
        meta.update(squeeze_meta())
    return exits.initialize(**{**dict(strategy_id=sid, direction='bullish', trigger_bar='2026-09-10T10:05',
                                   meta=meta, selection=selection()), **changes})


def quote(bid=1.2, stamp='2026-09-10T10:15:30'):
    return dict(symbol='XYZ',source_symbol='XYZ',bid=bid,ask=bid+.1,bid_date=stamp)


class StudyExitTests(unittest.TestCase):
    def test_all_26_are_covered_and_only_five_are_authored_timers(self):
        from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES
        from config.strategy_catalog import REVIEWED_STRATEGIES
        from config.research_order_specs import SPECS
        source_ids = {SPECS[sid].source if sid in SPECS else sid for sid in set(TESTED_RESEARCH_STRATEGIES)|set(REVIEWED_STRATEGIES)}
        self.assertEqual(source_ids, set(exits.PROTOCOL_BY_STRATEGY))
        self.assertEqual(26,len(exits.PROTOCOL_BY_STRATEGY))
        self.assertEqual(5,len(exits.TIMED))

    def test_each_declared_timer_uses_its_entry_quote_not_trigger_bar(self):
        for sid,minutes in exits.TIMED.items():
            state=initial(sid)
            decision=et(state['entry_quote_at'])+timedelta(minutes=minutes)
            self.assertEqual('collecting',exits.advance(state,now=decision-timedelta(seconds=1))['status'])
            pending=exits.advance(state,now=decision)
            self.assertEqual(decision.isoformat(),pending['decision_at'])
            priced=exits.advance(pending,now=decision+timedelta(seconds=10),quote=quote(3,decision.isoformat()))
            self.assertEqual('priced',priced['status'])
            self.assertEqual(96.7,exits.normalized_profit(priced))

    def test_actual_impulse_exit_matches_primary_and_first_loss_stays_latched(self):
        state=initial(); frame=candles(); frame.loc[5,'low']=97
        before=deepcopy(state)
        pending=exits.advance(state,frame=frame,now='2026-09-10T10:16')
        expected=impulse_exit.first_exit(frame,entry_at=state['trigger_bar'],entry_quote_at=state['entry_quote_at'],
                                        stop=98,target=104,direction='bullish',now='2026-09-10T10:16')
        self.assertEqual((pending['decision_at'],pending['reason']),(expected[0].isoformat(),expected[1]))
        frame.loc[5,'low']=99; frame.loc[10,'high']=105
        priced=exits.advance(pending,frame=frame,now='2026-09-10T10:16',quote=quote())
        self.assertEqual(-83.3,exits.normalized_profit(priced))
        self.assertEqual('underlying_stop',priced['reason'])
        self.assertEqual(priced,exits.advance(priced,frame=frame,now='2026-09-10T10:25',quote=quote(4)))
        self.assertEqual(before,state)

    def test_authored_timer_keeps_primary_five_minute_quote_window(self):
        state=initial('V2_SPY_TREND_CONT')
        decision=et(state['entry_quote_at'])+timedelta(minutes=30)
        pending=exits.advance(state,now=decision)
        received=decision+timedelta(minutes=2)
        priced=exits.advance(pending,now=received,quote=quote(3,received.isoformat()))
        self.assertEqual('priced',priced['status'])
        expired=exits.advance(pending,now=decision+timedelta(minutes=5,seconds=1))
        self.assertEqual('missing_quote',expired['status'])

    def test_other_structural_protocols_delegate_without_replacing_frames_or_metadata(self):
        for sid,protocol in exits.PROTOCOLS.items():
            if sid in context_orb_exit.PREMIUM_PROTOCOLS or sid==squeeze_exit.STRATEGY_ID:
                continue
            state=initial(sid); frame=candles(); frame.attrs['source_minutes']=15
            with patch.object(exits,'first_exit',return_value=None) as detect:
                self.assertEqual('collecting',exits.advance(state,frame=frame,now='2026-09-10T10:16')['status'])
            self.assertIs(frame,detect.call_args.args[1])
            self.assertEqual(protocol,detect.call_args.args[0])
            self.assertEqual(state['meta'],detect.call_args.kwargs['meta'])

    def test_nr7_and_atr10_whole_plan_partial_and_runner_use_real_bids(self):
        for sid in context_orb_exit.PREMIUM_PROTOCOLS:
            frame=candles('2026-09-10T10:05',350)
            state=exits.advance(initial(sid),frame=frame,now='2026-09-10T10:07',quote=quote(2.6,'2026-09-10T10:06:30'))
            self.assertIsNone(exits.normalized_profit(state))
            self.assertEqual(2.6,state['premium_path']['partial_bid'])
            priced=exits.advance(state,frame=frame,now='2026-09-10T10:08',quote=quote(4,'2026-09-10T10:07:30'))
            self.assertAlmostEqual(126.7,exits.normalized_profit(priced))
            self.assertEqual(4,priced['bid'])

    def test_structural_exit_has_priority_over_premium_target(self):
        frame=candles(); frame.loc[1,['low','close']]=[96,97]
        state=exits.advance(initial(context_orb_exit.STRATEGY_ID),frame=frame,
                            now='2026-09-10T10:07:45',quote=quote(4,'2026-09-10T10:07:30'))
        self.assertEqual('or_midpoint_close',state['reason'])
        self.assertIsNone(state['premium_path']['partial_bid'])

    def test_missing_bars_cannot_receive_premium_profit_credit(self):
        frame=candles().drop(index=1)
        state=exits.advance(initial(context_orb_exit.STRATEGY_ID),frame=frame,
                            now='2026-09-10T10:07',quote=quote(4,'2026-09-10T10:06:30'))
        self.assertEqual('collecting',state['status'])
        self.assertEqual(0,state['premium_path']['quote_count'])
        state=exits.advance(state,frame=frame,now='2026-09-10T10:13')
        self.assertEqual('unmeasurable',state['status'])

    def test_squeeze_target_and_hourly_exit_use_real_authored_rule(self):
        state=initial(squeeze_exit.STRATEGY_ID,trigger_bar='2026-09-10T10:30',selection=selection('2026-09-10T10:30:03'))
        frame=candles('2026-09-10T10:30',330)
        target=exits.advance(state,frame=frame,now='2026-09-10T10:31',quote=quote(5.1,'2026-09-10T10:30:30'))
        self.assertEqual('premium_target_150_pct',target['reason'])
        self.assertEqual(306.7,exits.normalized_profit(target))
        frame.loc[59,['low','close']]=[96,97]
        hourly=exits.advance(state,frame=frame,now='2026-09-10T11:30:30',quote=quote(1,'2026-09-10T11:30:10'))
        self.assertEqual('hourly_close_below_entry_sma20',hourly['reason'])

    def test_missing_late_future_wrong_contract_quotes_are_not_zero_or_wins(self):
        frame=candles(); frame.loc[5,'low']=97
        pending=exits.advance(initial(),frame=frame,now='2026-09-10T10:15')
        for q in (None,quote(stamp='2026-09-10T10:14:59'),quote(stamp='2026-09-10T10:17'),
                  {**quote(),'source_symbol':'WRONG'},quote(float('nan'))):
            state=exits.advance(pending,now='2026-09-10T10:16',quote=q)
            self.assertIsNone(exits.normalized_profit(state))
        late=exits.advance(pending,now='2026-09-10T10:20:01',quote=quote(4,'2026-09-10T10:20'))
        self.assertEqual('missing_quote',late['status'])

    def test_terminal_and_next_session_never_reprice(self):
        state=exits.advance(initial(),now='2026-09-11T10:16',quote=quote(4,'2026-09-11T10:16'))
        self.assertEqual('unmeasurable',state['status'])
        self.assertEqual('missed_session',state['reason'])
        self.assertIsNone(exits.normalized_profit(state))


class StudyStorageTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:'); self.conn.row_factory=sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('''CREATE TABLE shadow_candidates(candidate_id TEXT PRIMARY KEY,
            broker_account_id TEXT, strategy_id TEXT, direction TEXT, trigger_bar TEXT,
            observed_at TEXT, metadata_json TEXT, ticker TEXT)''')
        self.conn.execute(storage.CREATE_TABLE); self.conn.execute(storage.CREATE_INDEX)
        for cid,account in [('one','a'),('other','b')]:
            self.conn.execute('INSERT INTO shadow_candidates VALUES (?,?,?,?,?,?,?,?)',
                (cid,account,impulse_exit.STRATEGY_ID,'bullish','2026-09-10T10:05',
                 '2026-09-10T10:05:01',json.dumps(initial()['meta']),'META'))
        self.original=[tuple(row) for row in self.conn.execute('SELECT * FROM shadow_candidates')]

    def enroll(self,cid='one',account='a',chosen=None):
        return storage.record(self.conn,account=account,candidate_id=cid,selection=chosen or selection())

    def test_first_selection_immutable_accounts_isolated_primary_unchanged(self):
        self.assertTrue(self.enroll())
        before=storage.load(self.conn,account='a')
        self.assertFalse(self.enroll(chosen={**selection(),'contract':{**selection()['contract'],'ask':9}}))
        self.assertEqual(before,storage.load(self.conn,account='a'))
        self.assertFalse(self.enroll('other'))
        self.assertEqual([],storage.load(self.conn,account='b'))
        self.assertEqual(self.original,[tuple(row) for row in self.conn.execute('SELECT * FROM shadow_candidates')])

    def test_no_contract_remains_diagnostic_never_retried_into_winner(self):
        failed={**selection(),'contract':None,'status':'not_selected','reason':'no_expirations_in_window'}
        self.assertTrue(self.enroll(chosen=failed)); self.assertFalse(self.enroll())
        self.assertEqual([],storage.load(self.conn,account='a',active_only=True))

    def test_late_or_wrong_setup_cannot_be_repriced(self):
        for chosen in ({**selection(),'setup_at':'2026-09-09T10:05:01'},selection('2026-09-10T10:06:02')):
            with self.assertRaises(ValueError): self.enroll(chosen=chosen)

    def test_restart_stale_writer_and_latched_decision(self):
        self.enroll(); row=storage.load(self.conn,account='a')[0]
        frame=candles(); frame.loc[5,'low']=97
        pending=exits.advance(row['state'],frame=frame,now='2026-09-10T10:16')
        self.assertFalse(storage.save_transition(self.conn,account='b',row=row,state=pending))
        self.assertTrue(storage.save_transition(self.conn,account='a',row=row,state=pending))
        self.assertFalse(storage.save_transition(self.conn,account='a',row=row,state=pending))
        restarted=storage.load(self.conn,account='a')[0]
        with self.assertRaises(ValueError):
            storage.save_transition(self.conn,account='a',row=restarted,state={**pending,'reason':'winner'})
        priced=exits.advance(restarted['state'],now='2026-09-10T10:16',quote=quote())
        self.assertTrue(storage.save_transition(self.conn,account='a',row=restarted,state=priced))
        self.assertEqual([],storage.load(self.conn,account='a',active_only=True))

    def test_entry_identity_cannot_change_during_capture(self):
        self.enroll(); row=storage.load(self.conn,account='a')[0]
        for key,value in [('entry_ask',.5),('contract_symbol','OTHER'),('profile_version','new')]:
            with self.assertRaises(ValueError):
                storage.save_transition(self.conn,account='a',row=row,state={**row['state'],key:value})

    @contextmanager
    def connect(self):
        with self.conn:
            yield self.conn

    def capture(self, **changes):
        frame=candles(); frame.loc[5,'low']=97
        return storage.capture(**{**dict(connect=self.connect,account='a',bars_lookup=lambda ticker:frame,
            quote_lookup=lambda symbol:quote(),clock=lambda:et('2026-09-10T10:16')),**changes})

    def test_collector_completes_same_contract_and_commits_decision_before_quote(self):
        self.enroll()
        def check_latch(symbol):
            row=storage.load(self.conn,account='a')[0]
            self.assertEqual('pending_quote',row['state']['status'])
            self.assertEqual('underlying_stop',row['state']['reason'])
            self.assertEqual('XYZ',symbol)
            return quote()
        stats=self.capture(quote_lookup=check_latch)
        self.assertEqual(dict(rows=1,bars_reads=1,quote_reads=1,failed_rows=0),stats)
        self.assertEqual(-83.3,exits.normalized_profit(storage.load(self.conn,account='a')[0]['state']))
        self.assertEqual(0,self.capture()['rows'])
        self.assertEqual(self.original,[tuple(row) for row in self.conn.execute('SELECT * FROM shadow_candidates')])

    def test_40_overlapping_plays_share_reads_without_skipping_plays(self):
        for i in range(40):
            cid='play'+str(i)
            self.conn.execute('INSERT INTO shadow_candidates SELECT ?,broker_account_id,strategy_id,direction,trigger_bar,observed_at,metadata_json,ticker FROM shadow_candidates WHERE candidate_id=?',(cid,'one'))
            self.enroll(cid)
        self.enroll('other','b')
        stats=self.capture()
        self.assertEqual(dict(rows=40,bars_reads=1,quote_reads=1,failed_rows=0),stats)
        self.assertEqual(40,len([r for r in storage.load(self.conn,account='a') if r['state']['status']=='priced']))
        self.assertEqual('collecting',storage.load(self.conn,account='b')[0]['state']['status'])

    def test_failed_quote_keeps_latch_and_restart_prices_only_before_deadline(self):
        self.enroll()
        def offline(symbol): raise RuntimeError('offline')
        self.assertEqual(1,self.capture(quote_lookup=offline)['failed_rows'])
        self.assertEqual('pending_quote',storage.load(self.conn,account='a')[0]['state']['status'])
        stats=self.capture(clock=lambda:et('2026-09-10T10:21'))
        self.assertEqual(0,stats['quote_reads'])
        self.assertEqual('missing_quote',storage.load(self.conn,account='a')[0]['state']['status'])

    def test_slow_quote_uses_receipt_time_and_cannot_fake_timely_fill(self):
        self.enroll(); now=[et('2026-09-10T10:16')]
        def slow(symbol):
            now[0]=et('2026-09-10T10:21')
            return quote(4,'2026-09-10T10:16')
        self.capture(clock=lambda:now[0],quote_lookup=slow)
        state=storage.load(self.conn,account='a')[0]['state']
        self.assertEqual('missing_quote',state['status'])
        self.assertIsNone(exits.normalized_profit(state))

    def test_stopped_collector_performs_no_reads_or_writes(self):
        self.enroll(); before=storage.load(self.conn,account='a')
        self.assertEqual(dict(rows=0,bars_reads=0,quote_reads=0,failed_rows=0),self.capture(stopped=lambda:True))
        self.assertEqual(before,storage.load(self.conn,account='a'))

    def test_real_database_reopen_preserves_latch_after_provider_failure(self):
        self.enroll(); self.conn.commit()
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'study.db'
            disk=sqlite3.connect(path)
            self.conn.backup(disk); disk.close()
            @contextmanager
            def reopened():
                conn=sqlite3.connect(path); conn.row_factory=sqlite3.Row
                try:
                    with conn: yield conn
                finally: conn.close()
            def offline(symbol): raise RuntimeError('offline')
            self.assertEqual(1,self.capture(connect=reopened,quote_lookup=offline)['failed_rows'])
            with reopened() as conn:
                latched=storage.load(conn,account='a')[0]
                self.assertEqual('pending_quote',latched['state']['status'])
                with self.assertRaises(ValueError):
                    storage.save_transition(conn,account='a',row=latched,state={**latched['state'],'status':'collecting'})
            self.assertEqual(0,self.capture(connect=reopened)['failed_rows'])
            with reopened() as conn:
                final=storage.load(conn,account='a')[0]['state']
                self.assertEqual('priced',final['status'])
                self.assertEqual(latched['state']['decision_at'],final['decision_at'])
                self.assertEqual(self.original,[tuple(row) for row in conn.execute('SELECT * FROM shadow_candidates')])


if __name__=='__main__': unittest.main()
