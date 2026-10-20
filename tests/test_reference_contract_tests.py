from datetime import timedelta
import json
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from database.schema import _init_db_at
from database.reference_contract_tests import PROFILE, STRATEGIES, record, load, summary
from database.option_profit_protection import capture
from trading.entry.reference_contract_observation import observe
from strategy_health.option_profit_protection import STRATEGY_ID, RECOVERY_STRATEGY_ID, RECOVERY_PROTOCOL
from tests import test_option_profit_protection as fixtures
from tests.test_option_profit_protection import ENTRY, quote


class ReferenceTests(unittest.TestCase):
    def test_two_leg_previous_cohort_keeps_collecting_after_version_change(self):
        sid = 'V2_TSLA_TWO_LEG_TREND_PULLBACK'
        self.seed()
        with self.connect() as conn:
            conn.execute('UPDATE shadow_candidates SET strategy_id=? WHERE candidate_id=?', (sid, 'one'))
        record(candidate_id='one', strategy_id=sid, direction='bearish',
               meta={'strategy_version':'2.1.0'},
               contract=dict(symbol='XYZ', ask=2, bid=1.96), observed_at=ENTRY,
               details={'reason':'selected'})
        self.assertEqual('2.1.0', self.rows()['one']['strategy_version'])
        self.step(5401, 2.1)
        self.assertEqual('priced', self.rows()['one']['state']['control']['status'])

    def test_expanded_recovery_keeps_exact_version_in_reference_cohort(self):
        self.seed()
        with self.connect() as conn:
            conn.execute('UPDATE shadow_candidates SET strategy_id=? WHERE candidate_id=?',(RECOVERY_STRATEGY_ID,'one'))
        record(candidate_id='one',strategy_id=RECOVERY_STRATEGY_ID,direction='bearish',
               meta={'strategy_version':'2.1.0.research.2','v2_target':99,'v2_entry_reference':100},
               contract=dict(symbol='XYZ',ask=2,bid=1.96),observed_at=ENTRY,details={'reason':'selected'})
        self.assertEqual('2.1.0.research.2',self.rows()['one']['strategy_version'])
        self.step(30,bars_lookup=lambda _:[])
        self.assertEqual('collecting',self.rows()['one']['state']['control']['status'])

    setUpBase = fixtures.CaptureTests.setUp
    connect = fixtures.CaptureTests.connect
    seed = fixtures.CaptureTests.seed
    generic_rows = fixtures.CaptureTests.rows

    def setUp(self):
        self.setUpBase()
        p = patch('database.reference_contract_tests.get_conn', self.connect)
        p.start(); self.addCleanup(p.stop)

    def rows(self, account='a'):
        with self.connect() as conn: return load(conn, account, '2026-09-10')

    def reference(self, name='one', sid=STRATEGY_ID, contract=None, direction='bearish', **meta):
        version = STRATEGIES[sid][0]
        with self.connect() as conn:
            conn.execute('UPDATE shadow_candidates SET strategy_id=?,metadata_json=?,direction=? WHERE candidate_id=?',
                         (sid, json.dumps(dict(strategy_version=version, **meta)), direction, name))
        record(candidate_id=name, strategy_id=sid, direction=direction, meta=dict(strategy_version=version, **meta),
               contract=contract or dict(symbol='XYZ', ask=2, bid=1.96), observed_at=ENTRY,
               details={'reason': 'selected'})

    def step(self, seconds, bid=2.2, **kwargs):
        self.now = ENTRY+timedelta(seconds=seconds)
        self.lookup.return_value = quote(bid, seconds)
        capture(account='a', quote_lookup=self.lookup, clock=lambda:self.now, **kwargs)

    def test_same_candidate_can_keep_two_contracts_without_changing_primary_history(self):
        self.seed()
        # Preserve original experiment metadata; reference enrolment is separate.
        record(candidate_id='one', strategy_id=STRATEGY_ID, direction='bearish', meta={'strategy_version':'2.1.0'},
               contract=dict(symbol='OTHER',ask=4,bid=3.96), observed_at=ENTRY, details={'reason':'selected'})
        def lookup(symbol):
            q = quote(2.2 if symbol == 'XYZ' else 4.2, 30)
            return dict(q,symbol=symbol,source_symbol=symbol)
        self.lookup.side_effect = lookup
        self.step(30)
        self.assertEqual('XYZ', self.generic_rows()['one']['contract_symbol'])
        self.assertEqual('OTHER', self.rows()['one']['contract_symbol'])
        self.assertEqual(2, self.lookup.call_count)
        self.assertAlmostEqual(4.12, self.rows()['one']['state']['stop'])
        with self.connect() as conn:
            self.assertEqual(('XYZ',2),tuple(conn.execute("SELECT contract_symbol,ask FROM candidate_option_quote_observations WHERE observation_kind='entry'").fetchone()))

    def test_all_overlaps_share_quotes_across_both_cohorts_and_accounts_stay_separate(self):
        for i in range(40):
            self.seed(str(i))
            record(candidate_id=str(i), strategy_id=STRATEGY_ID, direction='bearish', meta={'strategy_version':'2.1.0'},
                   contract=dict(symbol='XYZ',ask=2,bid=1.96), observed_at=ENTRY, details={'reason':'selected'})
        self.seed('other', account='b'); self.reference('other')
        self.step(30)
        self.assertEqual(40,len(self.rows())); self.assertEqual(40,len(self.generic_rows()))
        self.lookup.assert_called_once_with('XYZ')
        self.assertIsNone(self.rows('b')['other']['state']['stop'])

    def test_90_minute_control_does_not_exit_at_30_or_poll_between(self):
        sid='V2_TSLA_TWO_LEG_TREND_PULLBACK'
        self.seed(); self.reference(sid=sid)
        self.step(1801)
        self.lookup.assert_not_called()
        self.assertEqual('collecting',self.rows()['one']['state']['control']['status'])
        self.step(5401,2.1)
        row=self.rows()['one']
        self.assertEqual('priced',row['state']['control']['status'])
        self.assertEqual('fixed_90m',row['state']['control']['reason'])
        self.assertEqual('not_tested',row['state']['trail']['status'])
        result=summary([{'candidate_id':'one'}],self.rows(),sid)
        self.assertEqual(1,result['option_results']);self.assertEqual(6.7,result['control']['net_pnl'])
        self.assertIsNone(result['profit_protection'])
        self.step(5500);self.lookup.assert_called_once()

    def test_failed_range_reference_uses_frozen_target_not_pre_target_premium_peak(self):
        self.seed(); self.reference(sid=RECOVERY_STRATEGY_ID,direction='bullish',v2_target=101,v2_entry_reference=100)
        frame=[dict(time=(ENTRY+timedelta(minutes=i)).isoformat(),open=100,high=102,low=99,close=101 if i==1 else 100) for i in range(4)]
        self.step(30,3,bars_lookup=lambda _:frame)
        self.assertIsNone(self.rows()['one']['state']['stop'])
        self.step(90,2.2,bars_lookup=lambda _:frame)
        self.step(120,2.2,bars_lookup=lambda _:frame)
        self.assertIsNone(self.rows()['one']['state']['stop'])
        self.step(150,2.2,bars_lookup=lambda _:frame)
        self.assertAlmostEqual(2.12,self.rows()['one']['state']['stop'])
        self.assertEqual(RECOVERY_PROTOCOL,self.rows()['one']['protocol'])

    def test_idempotent_migration_restart_and_no_replacing_first_selection(self):
        self.seed(); self.reference();self.step(30)
        before=self.rows();_init_db_at(self.path)
        self.reference(contract=dict(symbol='REPLACEMENT',ask=8,bid=7.96))
        self.assertEqual(before,self.rows())
        self.step(1861)
        self.assertEqual('missing_quote',self.rows()['one']['state']['control']['status'])
        count=self.lookup.call_count;self.step(2000);self.assertEqual(count,self.lookup.call_count)

    def test_reference_loss_test_is_stamped_and_does_not_enroll_legacy_primary(self):
        from strategy_health.initial_loss_protection import metadata, STATE_KEY
        self.seed()
        # Stamp only the separate reference cohort in this fixture.
        record(candidate_id='one',strategy_id=STRATEGY_ID,direction='bearish',
               meta={'strategy_version':'2.1.0',**metadata(STRATEGY_ID)},
               contract=dict(symbol='XYZ',ask=2,bid=1.96),observed_at=ENTRY,details={'reason':'selected'})
        self.step(30)
        self.assertIn(STATE_KEY,self.rows()['one']['state'])
        self.assertNotIn(STATE_KEY,self.generic_rows()['one']['state'])
        self.lookup.assert_called_once_with('XYZ')
        self.assertEqual(0,summary([{'candidate_id':'one'}],self.rows(),STRATEGY_ID)
                         ['profit_protection']['initial_loss_comparison']['paired_results'])

    def test_delayed_reference_selection_cannot_enroll_loss_test(self):
        from strategy_health.initial_loss_protection import metadata, STATE_KEY
        self.seed()
        record(candidate_id='one',strategy_id=STRATEGY_ID,direction='bearish',
               meta={'strategy_version':'2.1.0',**metadata(STRATEGY_ID)},
               contract=dict(symbol='XYZ',ask=2,bid=1.96),observed_at=ENTRY+timedelta(seconds=91),
               details={'reason':'selected'})
        self.assertNotIn(STATE_KEY,self.rows()['one']['state'])

    def test_unavailable_entry_and_version_mismatch_are_not_fake_zero_results(self):
        self.seed()
        args=dict(candidate_id='one',strategy_id=STRATEGY_ID,direction='bearish',contract=None,observed_at=ENTRY,details={'reason':'no_expirations'})
        record(**args,meta={'strategy_version':'2.0.0'});self.assertEqual({},self.rows())
        record(**args,meta={'strategy_version':'2.1.0'})
        result=summary([{'candidate_id':'one'}],self.rows(),STRATEGY_ID)
        self.assertEqual(1,result['tracked']);self.assertEqual(0,result['selected'])
        self.assertIsNone(result['control']['net_pnl']);self.assertIsNone(result['control']['profit_factor'])
        self.assertEqual({'no_expirations':1},result['selection_reasons'])
        self.step(1801);self.lookup.assert_called_once()  # Generic comparison only.

    def test_summary_does_not_mix_generic_or_other_strategy_rows(self):
        self.seed();self.reference();self.seed('orb');self.reference('orb',sid='V2_ORB_PULLBACK')
        self.step(30);self.step(60,2.1);self.step(90,2.08);self.step(1801,1.95)
        result=summary([{'candidate_id':'one'},{'candidate_id':'orb'}],self.rows(),STRATEGY_ID)
        self.assertEqual(PROFILE,result['profile_version']);self.assertEqual(1,result['tracked'])
        self.assertEqual(1,result['profit_protection']['paired_results'])
        self.assertEqual(13,result['profit_protection']['average_improvement'])
        self.assertEqual('2026-09-10T10:00:00',result['first_test_at'])

    def test_late_session_entry_cannot_claim_full_90_minute_test(self):
        self.seed(); sid='V2_ORB_PULLBACK'
        with self.connect() as conn: conn.execute('UPDATE shadow_candidates SET strategy_id=?',(sid,))
        record(candidate_id='one',strategy_id=sid,direction='bearish',meta={'strategy_version':'2.0.0'},
               contract=dict(symbol='XYZ',ask=2,bid=1.96), observed_at=ENTRY.replace(hour=15),details={'reason':'selected'})
        self.assertEqual('invalid_entry',self.rows()['one']['state']['control']['status'])

    def test_matrix_reference_survives_same_trigger_paper_candidate_without_mixing_results(self):
        from strategy_health.research_matrix import build_research_matrix
        sid='V2_SPY_AFTERNOON_FVG'
        self.seed('paper',source='tradier')
        self.seed('one');self.reference(sid=sid)
        with self.connect() as conn:
            conn.execute("UPDATE shadow_candidates SET ticker='SPY',strategy_id=?,metadata_json=?",
                         (sid,json.dumps({'strategy_version':'2.1.0'})))
        self.step(1801,2.1)
        settings={'active_broker_account_id':'a','watchlist':['SPY'], 'strategy_spy_afternoon_fvg_v2_enabled':True}
        with patch('database.get_conn',self.connect), patch('database._now_et',return_value=ENTRY), patch('config.get_settings',return_value=settings):
            matrix=build_research_matrix(90)
        strategy=next(r for r in matrix['strategies'] if r['strategy_id']==sid)
        pair=next(r for r in strategy['pairs'] if r['ticker']=='SPY')
        self.assertEqual(0,pair['option_results'])
        self.assertEqual(1,pair['reference_contract_test']['option_results'])
        self.assertEqual(6.7,pair['reference_contract_test']['control']['net_pnl'])
        self.assertEqual(0,strategy['current_evidence']['option_results'])

    def test_reference_is_collected_when_generic_expiration_window_has_no_contract(self):
        from trading.entry.candidate_observation import observe_candidate_contract
        self.seed()
        broker=SimpleNamespace(get_expirations=lambda *a,**kw:['2026-09-18'],
            get_option_chain=lambda *a:[dict(symbol='XYZ',strike=101,ask=2,bid=1.96)],
            get_option_quote=lambda _:quote(1.96,0))
        signal=SimpleNamespace(strategy_id=STRATEGY_ID,direction='bullish',meta={'strategy_version':'2.1.0','shadow_candidate_id':'one'})
        with self.connect() as conn: conn.execute("UPDATE shadow_candidates SET direction='bullish'")
        with patch('trading.entry.candidate_observation.record_router_candidate'), patch('trading.entry.candidate_observation.snapshot_candidate_plan'), \
             patch('trading.entry.candidate_observation.record_candidate_option_quote') as primary, \
             patch('trading.entry.candidate_observation.record_candidate_contract_alternative'), \
             patch('trading.entry.reference_contract_observation._now_et',return_value=ENTRY), \
             patch('trading.entry.contract._now_et',return_value=ENTRY), \
             patch('trading.research_contract_selection._now_et',return_value=ENTRY):
            # The observer's injectable clock is patched via its public entry
            # point so tests do not depend on the wall clock.
            with patch('trading.entry.reference_contract_observation.observe',side_effect=lambda **kw:observe(**kw,clock=lambda:ENTRY)):
                observe_candidate_contract(ticker='META',signal=signal,underlying_price=100,tradier=broker,
                    balance=4000,risk=Mock(),settings={},research_only=True)
        primary.assert_not_called()
        self.assertEqual('XYZ',self.rows()['one']['contract_symbol'])

    def test_delayed_entry_is_not_a_retroactive_trade(self):
        self.seed()
        record(candidate_id='one',strategy_id=STRATEGY_ID,direction='bearish',meta={'strategy_version':'2.1.0'},
               contract=dict(symbol='XYZ',ask=2,bid=1.96), observed_at=ENTRY+timedelta(seconds=91),details={'reason':'selected'})
        self.assertEqual('invalid_entry',self.rows()['one']['state']['control']['status'])
        self.assertEqual('entry_selection_delayed',self.rows()['one']['state']['control']['reason'])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.now=ENTRY
        self.broker=SimpleNamespace(get_expirations=Mock(return_value=['2026-09-11','2026-09-17','2026-09-24']),
            get_option_chain=Mock(side_effect=lambda ticker,expiry,kind:[dict(symbol=expiry,strike=101 if kind=='call' else 99,ask=2,bid=1.96)]),
            get_option_quote=Mock(side_effect=lambda symbol:dict(quote(1.96,int((self.now-ENTRY).total_seconds())),symbol=symbol,source_symbol=symbol)))
        self.args=dict(candidate_id='play',strategy_id=STRATEGY_ID,ticker='NVS',direction='bullish',price=100,
                       meta={'strategy_version':'2.1.0'},tradier=self.broker,clock=lambda:self.now)
        p=patch('trading.entry.reference_contract_observation.record');self.record=p.start();self.addCleanup(p.stop)
        p=patch('trading.entry.contract._now_et',return_value=ENTRY);p.start();self.addCleanup(p.stop)

    def test_uses_real_reviewed_selector_for_any_ticker_and_both_directions(self):
        for direction in ('bullish','bearish'):
            observe(**dict(self.args,direction=direction))
            args=self.record.call_args.kwargs
            self.assertEqual('2026-09-17',args['contract']['symbol'])
            self.assertEqual(7,args['details']['rules']['minimum_dte'])
            self.assertEqual(1000,args['details']['research_cap_dollars'])
            self.assertEqual('2026-09-10T10:00:00',args['details']['bid_at'])
        self.assertEqual(4,self.broker.get_option_chain.call_count)  # No 1-day expiry.

    def test_fresh_quote_must_match_symbol_time_price_and_spread(self):
        for changes in ({'source_symbol':'WRONG'},{'ask':11},{'ask':.79,'bid':.78},
                        {'bid_date':None},{'ask_date':None},{'bid':1},
                        {'bid_date':(ENTRY-timedelta(seconds=61)).isoformat()}):
            with self.subTest(changes=changes):
                q=dict(quote(1.96,0),symbol='2026-09-17',source_symbol='2026-09-17');q.update(changes)
                self.broker.get_option_quote.side_effect=None;self.broker.get_option_quote.return_value=q
                observe(**self.args)
                self.assertIsNone(self.record.call_args.kwargs['contract'])

    def test_cache_is_shared_across_matching_rules_but_expires(self):
        cache={};observe(**self.args,selection_cache=cache)
        self.now+=timedelta(seconds=4)
        observe(**dict(self.args,strategy_id='V2_SPY_AFTERNOON_FVG'),selection_cache=cache)
        self.broker.get_option_quote.assert_called_once()
        self.assertEqual(self.now,self.record.call_args.kwargs['observed_at'])
        self.now+=timedelta(seconds=2);observe(**self.args,selection_cache=cache)
        self.assertEqual(2,self.broker.get_option_quote.call_count)

    def test_read_errors_record_reason_without_an_order_or_fabricated_price(self):
        self.broker.get_option_quote.side_effect=RuntimeError('offline')
        observe(**self.args)
        self.assertIsNone(self.record.call_args.kwargs['contract'])
        self.assertEqual('api_error',self.record.call_args.kwargs['details']['reason'])

    def test_other_strategies_and_versions_do_not_get_silent_cohort_change(self):
        observe(**dict(self.args,strategy_id='CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'))
        observe(**dict(self.args,meta={'strategy_version':'2.0.0'}))
        self.record.assert_not_called();self.broker.get_option_quote.assert_not_called()
