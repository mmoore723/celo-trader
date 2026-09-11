from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from database.schema import _init_db_at
from database.option_profit_protection import capture, load
from strategy_health.option_profit_protection import PROTOCOL, STRATEGY_ID, VERSION, initialize, advance, summary, metadata

ENTRY = datetime(2026, 9, 10, 10, 0)


def quote(bid, seconds, **changes):
    return dict(symbol='XYZ', source_symbol='XYZ', bid=bid, ask=bid+.04,
                bid_date=(ENTRY+timedelta(seconds=seconds)).isoformat(),
                ask_date=(ENTRY+timedelta(seconds=seconds)).isoformat(), **changes)


class PolicyTests(unittest.TestCase):
    def step(self, state, seconds, bid=None, q=None):
        return advance(state, entry_at=ENTRY, ask=2, contract='XYZ', now=ENTRY+timedelta(seconds=seconds),
                       quote=q if q is not None else quote(bid, seconds) if bid is not None else None)

    def test_arm_prior_trail_later_fill_and_independent_control(self):
        s = initialize(ENTRY, 2, 1.96)
        s = self.step(s, 30, 2.20)
        self.assertAlmostEqual(2.12, s['stop'])
        self.assertEqual('collecting', s['trail']['status'])
        s = self.step(s, 60, 2.10)
        self.assertEqual('pending_quote', s['trail']['status'])
        self.assertNotIn('bid', s['trail'])
        s = self.step(s, 61, q=quote(2.10, 60))
        self.assertEqual('pending_quote', s['trail']['status'])
        s = self.step(s, 90, 2.08)
        self.assertEqual('priced', s['trail']['status'])
        self.assertEqual(2.08, s['trail']['bid'])
        self.assertEqual('collecting', s['control']['status'])
        s = self.step(s, 1801, 1.95)
        self.assertEqual('priced', s['control']['status'])
        self.assertEqual(1.95, s['control']['bid'])

    def test_stop_never_loosens_when_spread_widens(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 30, 2.20)
        q = quote(2.22, 60); q['ask'] = 2.42
        s = self.step(s, 60, q=q)
        self.assertAlmostEqual(2.12, s['stop'])

    def test_trigger_snapshot_keeps_crossing_separate_from_later_fill(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 30, 2.20)
        before = json.loads(json.dumps(s))
        s = self.step(s, 60, q=quote(2.10, 50))
        trigger = s['trail']['trigger']
        self.assertAlmostEqual(2.12, trigger['stop'])
        self.assertEqual(2.1, trigger['bid'])
        self.assertAlmostEqual(2.14, trigger['ask'])
        self.assertEqual('2026-09-10T10:00:50', trigger['bid_at'])
        self.assertEqual('2026-09-10T10:01:00', trigger['received_at'])
        self.assertEqual(before['last_received_at'], trigger['previous_received_at'])
        self.assertNotIn('trigger', before['trail'])
        self.assertNotIn('bid', s['trail'])
        s = self.step(json.loads(json.dumps(s)), 90, 2.08)
        self.assertEqual(trigger, s['trail']['trigger'])
        self.assertEqual(2.08, s['trail']['bid'])
        self.assertEqual('collecting', s['control']['status'])
        self.assertNotIn('trigger', s['control'])

    def test_trigger_snapshot_is_bounded_and_retained_if_fill_is_missing(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 30, 2.2)
        s = self.step(s, 60, 2.1)
        trigger = s['trail']['trigger'].copy()
        s = self.step(s, 121)
        self.assertEqual('missing_quote', s['trail']['status'])
        self.assertEqual(trigger, s['trail']['trigger'])
        self.assertLess(len(json.dumps(trigger)), 600)
        self.assertNotIn('bid', s['trail'])

    def test_unprofitable_path_cannot_create_profit_trail(self):
        s = initialize(ENTRY, 2, 1.96)
        for second in range(60, 1800, 60):
            s = self.step(s, second, 1.9)
        s = self.step(s, 1801, 1.8)
        self.assertEqual(s['control'], s['trail'])
        self.assertIsNone(s['stop'])

    def test_gap_invalidates_trail_not_control(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 121, 2.3)
        self.assertEqual('missing_path', s['trail']['status'])
        s = self.step(s, 1801, 2.1)
        self.assertEqual('priced', s['control']['status'])
        self.assertEqual('missing_path', s['trail']['status'])

    def test_late_exit_is_missing_not_a_fabricated_zero(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 1861, 0)
        self.assertEqual('missing_quote', s['control']['status'])
        self.assertNotIn('bid', s['control'])

    def test_bad_stale_future_and_wrong_symbol_quotes_rejected(self):
        for change in ({'symbol':'BAD'}, {'source_symbol':'BAD'}, {'ask':1}, {'bid':float('nan')},
                       {'bid_date':(ENTRY-timedelta(seconds=1)).isoformat()},
                       {'bid_date':(ENTRY+timedelta(seconds=90)).isoformat()}, {'ask_date':None}):
            with self.subTest(change=change):
                q=quote(2.2, 30); q.update(change)
                s = self.step(initialize(ENTRY, 2, 1.96), 30, q=q)
                self.assertEqual(0, s['quote_count'])
                self.assertIsNone(s['stop'])

    def test_repeated_exchange_quote_does_not_extend_coverage(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 30, 2.2)
        s = self.step(s, 60, q=quote(2.2, 30))
        self.assertEqual(1, s['quote_count'])
        s = self.step(s, 151, 2.3)
        self.assertEqual('missing_path', s['trail']['status'])

    def test_no_retroactive_fill_when_trigger_quote_has_older_exchange_stamp(self):
        s = self.step(initialize(ENTRY, 2, 1.96), 30, 2.2)
        s = self.step(s, 60, q=quote(2.1, 50))
        self.assertEqual('2026-09-10T10:01:00', s['trail']['decision_at'])
        s = self.step(s, 65, q=quote(2.1, 55))
        self.assertEqual('pending_quote', s['trail']['status'])

    def test_entry_validation_session_boundary_and_metadata_scope(self):
        for ask, bid in ((0,0), (float('inf'),1), (2,3), (None,1)):
            self.assertEqual('invalid_entry', initialize(ENTRY,ask,bid)['trail']['status'])
        self.assertEqual('invalid_entry', initialize(ENTRY.replace(hour=15,minute=26),2,1.9)['trail']['status'])
        self.assertEqual({}, metadata('OTHER'))
        self.assertEqual(PROTOCOL, metadata(STRATEGY_ID)['profit_protection_protocol'])

    def test_observer_stamps_before_persisting_only_for_research(self):
        from trading.entry.candidate_observation import observe_candidate_contract
        for research in (True,False):
            signal=SimpleNamespace(strategy_id=STRATEGY_ID,meta={})
            with patch('trading.entry.candidate_observation.record_router_candidate') as record:
                def check(*_):
                    self.assertEqual(research,'profit_protection_protocol' in signal.meta)
                    self.assertEqual(research,'initial_loss_protocol' in signal.meta)
                record.side_effect=check
                observe_candidate_contract(ticker='SPY',signal=signal,underlying_price=700,tradier=Mock(),
                    balance=4000,risk=Mock(),settings={},research_only=research)
            record.assert_called_once()

    def test_zero_bid_can_price_loss_and_utc_epoch_quote_dates_work(self):
        q=quote(0,1801)
        # September ET is UTC-4; actual API returns epoch milliseconds.
        epoch=int(datetime.fromisoformat('2026-09-10T14:30:01+00:00').timestamp()*1000)
        q.update(bid_date=epoch,ask_date=epoch)
        s=self.step(initialize(ENTRY,2,1.96),1801,q=q)
        self.assertEqual('priced',s['control']['status'])
        self.assertEqual(0,s['control']['bid'])


class CaptureTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'test.db'; _init_db_at(self.path)
        p=patch('database.option_profit_protection.get_conn', self.connect); p.start(); self.addCleanup(p.stop)
        self.now=ENTRY+timedelta(seconds=30)
        self.lookup=Mock(return_value=quote(2.2,30))

    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.path); conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()

    def seed(self, name='one', account='a', protocol=PROTOCOL, version=VERSION, source='tradier_research_contract_v1', extra_meta=None):
        with self.connect() as conn:
            conn.execute('''INSERT INTO shadow_candidates
                (candidate_id,observed_at,trigger_bar,ticker,strategy_id,direction,confidence,broker_account_id,metadata_json)
                VALUES (?,? ,?,'META',?,'bearish',.7,?,?)''',
                (name,ENTRY.isoformat(),ENTRY.isoformat(),STRATEGY_ID,account,json.dumps(dict(strategy_version=version,profit_protection_protocol=protocol,**(extra_meta or {})))))
            conn.execute('''INSERT INTO candidate_option_quote_observations
                (candidate_id,observed_at,observation_kind,contract_symbol,ask,bid,source) VALUES (?,?,'entry','XYZ',2,1.96,?)''',
                (name,ENTRY.isoformat(),source))

    def capture(self, **kwargs):
        capture(account='a', quote_lookup=self.lookup, clock=lambda:self.now, **kwargs)

    def rows(self):
        with self.connect() as conn: return load(conn,'a','2026-09-10')

    def test_only_new_matching_version_research_account_all_overlaps(self):
        for i in range(40): self.seed(str(i))
        self.seed('old',protocol=None); self.seed('other',account='b')
        self.seed('paper',source='tradier'); self.seed('version',version='2.0.0')
        self.capture()
        self.assertEqual(40,len(self.rows()))
        self.lookup.assert_called_once_with('XYZ')
        self.assertTrue(all(r['state']['stop'] is not None for r in self.rows().values()))

    def test_restart_migration_and_stopped_capture(self):
        self.seed(); self.capture(stopped=lambda:True); self.assertEqual({},self.rows())
        self.capture(); before=self.rows(); _init_db_at(self.path)
        self.capture(); self.assertEqual(before,self.rows())

    def test_trigger_snapshot_persists_through_database_reload(self):
        self.seed(); self.capture()
        self.now=ENTRY+timedelta(seconds=60)
        self.lookup.return_value=quote(2.1,50); self.capture()
        trigger=self.rows()['one']['state']['trail']['trigger']
        self.assertEqual(2.1,trigger['bid'])
        _init_db_at(self.path)
        self.now=ENTRY+timedelta(seconds=90)
        self.lookup.return_value=quote(2.08,90); self.capture()
        leg=self.rows()['one']['state']['trail']
        self.assertEqual(trigger,leg['trigger'])
        self.assertEqual(2.08,leg['bid'])
        self.assertEqual(3,self.lookup.call_count)

    def test_failure_no_quote_storm_and_eventual_expiration(self):
        self.seed(); self.seed('two'); self.lookup.side_effect=RuntimeError('offline')
        self.capture(); self.lookup.assert_called_once()
        self.now=ENTRY+timedelta(minutes=32); self.capture()
        self.assertEqual(1,self.lookup.call_count)
        self.assertTrue(all(r['state']['trail']['status']=='missing_path' for r in self.rows().values()))

    def test_paired_summary_after_costs_and_unpaired_not_zero(self):
        self.seed(); self.seed('missing'); self.capture()
        self.now=ENTRY+timedelta(seconds=60); self.lookup.return_value=quote(2.1,60); self.capture()
        self.now=ENTRY+timedelta(seconds=90); self.lookup.return_value=quote(2.08,90); self.capture()
        self.now=ENTRY+timedelta(seconds=1801); self.lookup.return_value=quote(1.95,1801); self.capture()
        rows=self.rows(); rows['missing']['state']['control']={'status':'missing_quote'}
        result=summary([{'candidate_id':'one'}, {'candidate_id':'missing'}],rows)
        self.assertEqual(1,result['paired_results']); self.assertEqual(1,result['unpaired'])
        self.assertEqual(-8.3,result['control']['net_pnl'])
        self.assertEqual(4.7,result['trail']['net_pnl'])
        self.assertEqual(13,result['average_improvement'])
        self.assertIsNone(summary([],rows)['average_improvement'])

    def test_closed_rows_do_not_refetch_and_scope_does_not_leak(self):
        self.seed(); self.capture(); self.now=ENTRY+timedelta(minutes=32); self.capture()
        n=self.lookup.call_count; before=self.rows(); self.capture()
        self.assertEqual(n,self.lookup.call_count); self.assertEqual(before,self.rows())
        with self.connect() as conn: self.assertEqual({},load(conn,'b','2026-09-10'))

    def test_loss_experiment_new_stamp_all_overlaps_and_account_isolation(self):
        from strategy_health.initial_loss_protection import metadata, STATE_KEY, outcomes, comparison
        for i in range(40): self.seed(str(i), extra_meta=metadata(STRATEGY_ID))
        self.seed('legacy'); self.seed('other', account='b', extra_meta=metadata(STRATEGY_ID))
        self.capture()
        self.lookup.assert_called_once_with('XYZ')
        self.assertNotIn(STATE_KEY, self.rows()['legacy']['state'])
        self.assertEqual(40, sum(STATE_KEY in r['state'] for r in self.rows().values()))
        self.now=ENTRY+timedelta(seconds=60); self.lookup.return_value=quote(2.1,60); self.capture()
        self.now=ENTRY+timedelta(seconds=90); self.lookup.return_value=quote(2.08,90); self.capture()
        # Profit trail is finished, but loss-only must keep observing before cap.
        before=self.lookup.call_count
        self.now=ENTRY+timedelta(seconds=120); self.lookup.return_value=quote(1.59,120); self.capture()
        self.assertEqual(before+1,self.lookup.call_count)
        extra=self.rows()['0']['state'][STATE_KEY]
        self.assertEqual('pending_quote',outcomes(extra)['loss_only']['status'])
        _init_db_at(self.path)
        self.now=ENTRY+timedelta(seconds=150); self.lookup.return_value=quote(1.55,150); self.capture()
        extra=self.rows()['0']['state'][STATE_KEY]
        self.assertEqual(1.55,outcomes(extra)['loss_only']['bid'])
        self.now=ENTRY+timedelta(seconds=1801); self.lookup.return_value=quote(2.2,1801); self.capture()
        result=comparison(list(self.rows().values()))
        self.assertEqual(40,result['paired_results'])
        self.assertAlmostEqual(-1932,result['arms']['loss_only']['net_pnl'])
        before=self.lookup.call_count; self.capture(); self.assertEqual(before,self.lookup.call_count)
        with self.connect() as conn: self.assertEqual({},load(conn,'b','2026-09-10'))

    def test_slow_quote_fetch_cannot_price_after_deadline(self):
        self.seed(); self.now=ENTRY+timedelta(seconds=1801)
        def slow(_):
            self.now=ENTRY+timedelta(seconds=1861)
            return quote(2.2,1861)
        self.lookup.side_effect=slow; self.capture()
        self.assertEqual('missing_quote',self.rows()['one']['state']['control']['status'])
