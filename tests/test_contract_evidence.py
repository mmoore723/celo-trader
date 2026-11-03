from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

from broker.tradier_chain import TradierChainMixin
from trading.diagnostics import contract_evidence as evidence
from trading.entry.contract import select_reviewed_v2_contract

NOW = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
SETTINGS = dict(active_broker_account_id='paper-account', paper_trading=True, broker_provider='alpaca')
SID = 'V2_SPY_TREND_CONT'


def quote(symbol='OPT'):
    return dict(symbol=symbol, bid=1.94, ask=2.0, bidsize=2, asksize=3,
                bid_date=NOW.timestamp()*1000, ask_date=NOW.timestamp()*1000,
                greeks={'delta': .45, 'updated_at': '2026-09-14 13:00:00'})


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.target = Path(folder.name) / 'evidence.sqlite3'
        for name, value in [('get_current_user_id', 'test-user'), ('clock', NOW), ('path', self.target)]:
            mock = patch.object(evidence, name, return_value=value)
            mock.start(); self.addCleanup(mock.stop)

    def record(self, candidate='one', **kwargs):
        trace = evidence.TraceReader(None)
        trace.chains = [dict(expiry='2026-09-21', rows=[dict(quote(), evidence=quote())])]
        args = dict(trace=trace, settings=SETTINGS, candidate_id=candidate, strategy_id=SID,
                    ticker='SPY', version='2.1.0', direction='bullish', price=100,
                    maximum=750, contract={'symbol': 'OPT', 'ask': 2},
                    info={'shadow_contract_leaderboard': [{'symbol': 'OPT'}]},
                    cohort='execution_preview', target=self.target)
        args.update(kwargs)
        return evidence.record(**args)

    def read(self, table):
        with evidence.connect(self.target) as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM ' + table)]

    def test_records_source_fields_without_mutation_or_default_greeks(self):
        self.assertTrue(self.record())
        payload = json.loads(zlib.decompress(self.read('selections')[0]['payload']))
        self.assertEqual(.45, payload['chains'][0]['rows'][0]['evidence']['greeks']['delta'])
        self.assertEqual(2, payload['chains'][0]['rows'][0]['evidence']['bidsize'])
        self.assertFalse(payload['native_fill_confirmed'])
        self.assertEqual('requires_verified_greek_timestamp', payload['delta_ranking_status'])

    def test_duplicate_candidates_do_not_reprice_and_cohorts_stay_separate(self):
        self.record()
        self.assertFalse(self.record(contract={'symbol': 'NEW', 'ask': 9}))
        self.record(cohort='research_native_contract_rules')
        self.assertEqual(2, len(self.read('selections')))
        self.assertEqual(['OPT'], [r['symbol'] for r in self.read('watches')])

    def test_all_seven_native_pairs_and_out_of_scope_rejection(self):
        for sid, tickers in evidence.PAIRS.items():
            for ticker in tickers:
                self.assertTrue(self.record(sid+ticker, strategy_id=sid, ticker=ticker))
        self.assertEqual(7, len(self.read('selections')))
        self.assertFalse(self.record('bad', ticker='META'))

    def test_account_and_mode_isolation(self):
        self.record()
        reader = Mock()
        for changed in [dict(SETTINGS, active_broker_account_id='other'),
                        dict(SETTINGS, paper_trading=False)]:
            self.assertEqual(0, evidence.capture(reader=reader, settings=changed, now=NOW, target=self.target))
        reader.get_research_option_quotes.assert_not_called()

    def test_many_overlapping_plays_share_one_symbol_and_minute_across_restart(self):
        for i in range(40):
            self.record(str(i))
        reader = Mock()
        reader.get_research_option_quotes.return_value = {'OPT': quote()}
        for _ in range(2):
            evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        reader.get_research_option_quotes.assert_called_once_with(['OPT'])
        self.assertEqual([], json.loads(self.read('quotes')[0]['payload'])['issues'])

    def test_missing_quote_is_saved_not_a_zero_price_or_fabricated_fill(self):
        self.record()
        reader = Mock()
        reader.get_research_option_quotes.return_value = {}
        evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        row = json.loads(self.read('quotes')[0]['payload'])
        self.assertEqual({}, row['quote'])
        self.assertEqual(['quote_missing'], row['issues'])

    def test_future_stale_missing_size_and_crossed_quotes_are_not_valid(self):
        for changed, expected in [({'bid_date': (NOW+timedelta(seconds=1)).timestamp()*1000}, 'stale_or_future_bid_date'),
                                  ({'ask_date': (NOW-timedelta(seconds=61)).timestamp()*1000}, 'stale_or_future_ask_date'),
                                  ({'bidsize': None}, 'missing_or_invalid_bidsize'),
                                  ({'ask': 1}, 'crossed_quote')]:
            self.assertIn(expected, evidence.quote_issues(dict(quote(), **changed), NOW))
        with self.assertRaises(ValueError):
            evidence._time('2026-09-14 13:00:00')

    def test_capture_failure_no_throw_and_no_order_methods(self):
        self.record()
        reader = Mock()
        reader.get_research_option_quotes.side_effect = RuntimeError('offline')
        evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        self.assertEqual(['batch_read_failed'], json.loads(self.read('quotes')[0]['payload'])['issues'])
        self.assertEqual(['get_research_option_quotes'], [c[0] for c in reader.mock_calls])

    def test_storage_cap_preserves_existing_records(self):
        self.record()
        with patch.object(evidence, 'MAX_BYTES', 16384):
            with self.assertRaises((ValueError, __import__('sqlite3').DatabaseError)):
                self.record('two')
        self.assertEqual(1, len(self.read('selections')))

    def test_capture_resumes_after_budget_increase_without_rewriting_evidence(self):
        self.record()
        original = [dict(r) for r in self.read('selections')]
        with patch.object(evidence,'MAX_BYTES',16384):
            with self.assertRaises((ValueError,__import__('sqlite3').DatabaseError)):
                self.record('blocked')
        self.assertTrue(self.record('new'))
        self.assertEqual(original[0],dict(self.read('selections')[0]))
        self.assertEqual(2,len(self.read('selections')))

    def test_symlink_rejected_and_stop_prevents_reads(self):
        other = self.target.with_name('link.sqlite3')
        other.symlink_to(self.target)
        with self.assertRaises(ValueError):
            self.record(target=other)
        self.record()
        reader = Mock()
        self.assertEqual(0, evidence.capture(reader=reader, settings=SETTINGS, stopped=lambda: True, target=self.target))
        reader.get_research_option_quotes.assert_not_called()

    def test_over_budget_chain_is_explicit_not_silently_truncated(self):
        reader = Mock()
        reader.get_option_chain.return_value = [{'symbol': 'OPT'}] * 3
        trace = evidence.TraceReader(reader)
        with patch.object(evidence, 'MAX_CHAIN_ROWS', 2):
            self.assertIs(reader.get_option_chain.return_value, trace.get_option_chain('SPY', '2026-09-21', 'call'))
        self.record(trace=trace)
        payload = json.loads(zlib.decompress(self.read('selections')[0]['payload']))
        self.assertEqual('chain_budget_exceeded', payload['coverage'])
        self.assertEqual([], payload['chains'])

    def test_wrapper_preserves_control_selection_for_all_seven_pairs(self):
        for sid, tickers in evidence.PAIRS.items():
            for ticker in tickers:
                expiry = '2026-09-18' if sid.startswith('CTX_') else '2026-09-21'
                chain = [dict(symbol='ONE', strike=101, ask=2, bid=1.94, open_interest=100, volume=20),
                         dict(symbol='TWO', strike=102, ask=1.8, bid=1.74, open_interest=200, volume=10)]
                reader = Mock()
                reader.get_expirations.return_value = [expiry]
                reader.get_option_chain.return_value = deepcopy(chain)
                with patch('trading.entry.contract._now_et', return_value=NOW):
                    direct = select_reviewed_v2_contract(reader, ticker, 'bullish', 100, 750, True, strategy_id=sid)
                    traced = select_reviewed_v2_contract(evidence.TraceReader(reader), ticker, 'bullish', 100, 750, True, strategy_id=sid)
                self.assertEqual(direct, traced)
                self.assertEqual(chain, reader.get_option_chain.return_value)

    def test_worker_observer_reaches_all_seven_pairs_and_freezes_versions(self):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        from trading.research_versions import evidence_version
        reader = Mock()
        reader.get_option_chain.return_value = [dict(symbol='OPT', strike=101,
            bid=1.94, ask=2, open_interest=1000, volume=10)]
        with patch('config.research_snapshot.current_snapshot', return_value=SETTINGS), \
                patch('trading.entry.contract._now_et', return_value=NOW):
            for sid, tickers in evidence.PAIRS.items():
                for ticker in tickers:
                    reader.get_expirations.return_value = [
                        '2026-09-18' if sid.startswith('CTX_') else '2026-09-21']
                    signal = SimpleNamespace(strategy_id=sid, direction='bullish', meta=dict(
                        strategy_version=evidence_version(sid, REVIEWED_STRATEGIES[sid].version),
                        shadow_candidate_id=sid+ticker))
                    evidence.observe_research(signal=signal, ticker=ticker, price=100,
                                              reader=reader, settings=SETTINGS)
            before = reader.get_option_chain.call_count
            evidence.observe_research(signal=signal, ticker=ticker, price=100,
                                      reader=reader, settings=SETTINGS)
            self.assertEqual(before, reader.get_option_chain.call_count)
        rows = self.read('selections')
        self.assertEqual(7, len(rows))
        self.assertTrue(all(r['cohort'] == 'research_native_contract_rules' for r in rows))
        versions = [json.loads(zlib.decompress(r['payload']))['strategy_version'] for r in rows]
        self.assertIn('0.2.0.research.2', versions)

    def test_delta_watch_does_not_change_control_and_rejects_missing_or_ineligible(self):
        trace = evidence.TraceReader(None)
        rows = []
        for symbol, delta, ask in [('DELTA', .51, 2), ('MISSING', None, 2), ('EXPENSIVE', .5, 20)]:
            rows.append(dict(symbol=symbol, strike=101, ask=ask, bid=ask-.05,
                             evidence={'greeks': {'delta': delta, 'updated_at': 'ambiguous'}}))
        trace.chains = [dict(expiry='2026-09-21', rows=rows)]
        self.record(trace=trace)
        data = json.loads(zlib.decompress(self.read('selections')[0]['payload']))
        self.assertEqual('OPT', data['control']['symbol'])
        self.assertEqual('DELTA', data['delta_watch']['symbol'])
        self.assertFalse(data['delta_watch']['timestamp_validated'])
        self.assertEqual({'OPT', 'DELTA'}, {r['symbol'] for r in self.read('watches')})

    def test_worker_refuses_unpinned_or_changed_account_context(self):
        signal = SimpleNamespace(strategy_id=SID, direction='bullish', meta=dict(
            strategy_version='2.1.0', shadow_candidate_id='one'))
        reader = Mock()
        for pinned in [None, dict(SETTINGS, active_broker_account_id='other')]:
            with patch('config.research_snapshot.current_snapshot', return_value=pinned):
                evidence.observe_research(signal=signal, ticker='SPY', price=100,
                                          reader=reader, settings=SETTINGS)
        reader.get_option_chain.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_missing_samples_are_not_backfilled(self):
        self.record()
        reader = Mock()
        reader.get_research_option_quotes.return_value = {'OPT': quote()}
        evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        with patch.object(evidence, 'clock', return_value=NOW+timedelta(minutes=5)):
            evidence.capture(reader=reader, settings=SETTINGS, now=NOW+timedelta(minutes=5), target=self.target)
        self.assertEqual(2, len(self.read('quotes')))
        self.assertIn('stale_or_future_bid_date', json.loads(self.read('quotes')[1]['payload'])['issues'])

    def test_read_budget_and_fair_rotation(self):
        self.record()
        with evidence.connect(self.target) as conn:
            conn.executemany('INSERT INTO watches VALUES (?,?,?)',
                [(evidence.identity(SETTINGS), '2026-09-14', f'OPT{i:03}') for i in range(305)])
        reader = Mock()
        reader.get_research_option_quotes.return_value = {}
        evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        self.assertEqual(3, reader.get_research_option_quotes.call_count)
        self.assertTrue(all(len(c.args[0]) <= 100 for c in reader.get_research_option_quotes.call_args_list))
        evidence.capture(reader=reader, settings=SETTINGS, now=NOW, target=self.target)
        self.assertEqual(306, len(self.read('quotes')))


class BrokerEvidenceTests(unittest.TestCase):
    def test_batch_preserves_nulls_and_source_timestamps(self):
        broker = TradierChainMixin()
        broker.api_key = 'fixture'
        raw = quote()
        raw['asksize'] = None
        broker._get = Mock(return_value={'quotes': {'quote': [raw, quote('UNREQUESTED')]}})
        got = broker.get_research_option_quotes(['OPT'])
        self.assertEqual({'OPT'}, set(got))
        self.assertIsNone(got['OPT']['asksize'])
        self.assertEqual(raw['greeks'], got['OPT']['greeks'])
        with self.assertRaises(ValueError):
            broker.get_research_option_quotes([str(i) for i in range(101)])

    def test_execution_chain_values_unchanged_and_missing_greek_explicit_in_evidence(self):
        broker = TradierChainMixin()
        broker.api_key = 'fixture'
        broker._get = Mock(return_value={'options': {'option': dict(quote(), strike=101,
            option_type='call', open_interest=1000, greeks=None)}})
        row = broker.get_option_chain('SPY', '2026-09-21')[0]
        self.assertEqual(0, row['delta'])  # Existing execution compatibility.
        self.assertIsNone(row['evidence']['greeks'])
        self.assertEqual(2, row['evidence']['bidsize'])


if __name__ == '__main__':
    unittest.main()
