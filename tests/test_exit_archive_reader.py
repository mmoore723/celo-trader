from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from strategy_health.exit_archive_reader import ExitArchiveReader, timestamp
from strategy_health.fast_capture import Registry
from strategy_health.paired_exit_accounting import Entry, Scope, Intent, Pricing, compare
from trading.decision_trace import _write
from strategy_health.session_capture import Archive, SOURCE

T = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
C = 'SPY261120C00600000'


class ArchiveReaderTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.registry = Registry(self.root / 'fast_capture')
        self.addCleanup(self.registry.db.close)
        self.entry = Entry(Scope('a', 'paper', 'test', 'SPY', 'v1', 'exp'),
                           '1', C, T, D(2), 1, D(0), 'fill-1')
        self.registration = self.registry.register(account='a', mode='paper', strategy='test',
            ticker='SPY', version='v1', symbol=C, entry_at=T.isoformat(),
            until_at=(T+timedelta(hours=1)).isoformat(), origin='broker_trade', origin_id='1',
            policy='native-v1', metadata={}, now=T)
        self.reader = ExitArchiveReader(self.root)

    def record(self, seconds=5, **changes):
        at=T+timedelta(seconds=seconds)
        raw=dict(symbol=C,bid=2.5,ask=2.6,bidsize=5,asksize=5,
                 bid_date=int(at.timestamp()*1000),ask_date=int(at.timestamp()*1000))
        raw.update(changes)
        self.registry.record([C], {'quotes':{'quote':[raw]}}, at, at)

    def read(self, **kw):
        return self.reader.option_quotes(kw.get('entry',self.entry),self.registration,T+timedelta(seconds=30))

    def event(self):
        return dict(event_id='event',cycle_id='cycle',recorded_at=(T+timedelta(seconds=5)).isoformat(),
            mode='paper',trade=dict(id=1,broker_account_id='a',strategy_id='test',ticker='SPY',
                contract_symbol=C,strategy_context_json=json.dumps({'strategy_version':'v1'})),
            stage='cycle_start',snapshot={'complete':True,'data':{},'issues':[]})

    def test_real_writer_to_priced_pair(self):
        self.record(5); self.record(10)
        read=self.read(); self.assertEqual(2,len(read['quotes']))
        result=compare(self.entry,[Intent(T+timedelta(seconds=10),1,'native','n')],
            [Intent(T+timedelta(seconds=5),1,'candidate','c')],read['quotes'],
            Pricing(5,5,10,D('.01'),D('.5'),'fees'),baseline_policy='native',candidate_policy='c')
        self.assertEqual('evaluable',result['status'])
        self.assertFalse(read['coverage_verified']); self.assertFalse(read['entry_levels_verified'])
        self.assertEqual(T+timedelta(seconds=5),read['quotes'][0].bid_at)

    def test_scope_isolation(self):
        for field,value in [('account','b'),('mode','live'),('strategy','other'),('ticker','QQQ'),('version','v2')]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'scope_mismatch'):
                self.read(entry=replace(self.entry,scope=replace(self.entry.scope,**{field:value})))
        for field,value in [('trade_id','2'),('contract','other')]:
            with self.assertRaisesRegex(ValueError,'scope_mismatch'):
                self.read(entry=replace(self.entry,**{field:value}))

    def test_missing_timestamp_not_replaced_by_receipt(self):
        self.record(bid_date=None)
        r=self.read(); self.assertEqual([],r['quotes'])
        self.assertIn('missing_source_timestamp',r['rejected'][0]['reason'])

    def test_missing_size_not_invented(self):
        self.record(bidsize=None)
        self.assertEqual('missing_valid_bid_size',self.read()['rejected'][0]['reason'])

    def test_bounded_query_never_silently_truncates(self):
        self.record(5); self.record(10); self.reader=ExitArchiveReader(self.root,max_rows=1)
        with self.assertRaisesRegex(ValueError,'row_limit'): self.read()

    def test_read_does_not_mutate_records(self):
        self.record()
        before=list(self.registry.db.iterdump()); self.read()
        self.assertEqual(before,list(self.registry.db.iterdump()))
        with self.reader._open('fast_capture/fast_capture.sqlite3') as db:
            with self.assertRaises(Exception): db.execute('DELETE FROM observations')

    def test_absent_archive_not_created(self):
        with self.assertRaisesRegex(ValueError,'missing_archive'):
            self.reader.decision_events(self.entry,T+timedelta(seconds=30))
        self.assertFalse((self.root/'exit_decisions').exists())

    def test_research_registration_not_broker_fill(self):
        with self.registry.db:
            self.registry.db.execute("UPDATE registrations SET origin='research_selection'")
        with self.assertRaisesRegex(ValueError,'scope_mismatch'): self.read()

    def test_real_decision_writer_and_version_guard(self):
        event=self.event(); _write(self.root/'exit_decisions',event)
        r=self.reader.decision_events(self.entry,T+timedelta(seconds=30))
        self.assertEqual([event],r['events']); self.assertFalse(r['decision_coverage_verified'])
        with self.assertRaisesRegex(ValueError,'version_mismatch'):
            self.reader.decision_events(replace(self.entry,scope=replace(self.entry.scope,version='v2')),T+timedelta(seconds=30))

    def test_payload_identity_corruption_blocked(self):
        event=self.event(); _write(self.root/'exit_decisions',event)
        import sqlite3
        with sqlite3.connect(self.root/'exit_decisions/decisions.sqlite3') as db:
            event['trade']['contract_symbol']='wrong'
            db.execute('UPDATE decisions SET payload=?',(json.dumps(event),))
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            self.reader.decision_events(self.entry,T+timedelta(seconds=30))

    def test_aware_offset_normalization_and_naive_rejection(self):
        self.assertEqual(T,timestamp('2026-11-09T10:00:00-05:00'))
        with self.assertRaisesRegex(ValueError,'aware_timestamp'): timestamp('2026-11-09T10:00:00')

    def test_entry_clock_mismatch_blocked(self):
        with self.assertRaisesRegex(ValueError,'entry_time_mismatch'):
            self.read(entry=replace(self.entry,filled_at=T+timedelta(seconds=1)))

    def original_entry(self, **level_changes):
        import sqlite3
        from database.schema import _CREATE_TRADES, _CREATE_SHADOW_CANDIDATES
        levels=dict(schema=1,status='captured',support=590,resistance=None,
            source_completed_at=(T-timedelta(minutes=2)).isoformat(),
            recorded_at=(T-timedelta(seconds=30)).isoformat(),updates_after_entry=False)
        levels.update(level_changes)
        meta=dict(strategy_version='v1',structural_levels=levels)
        with sqlite3.connect(self.root/'trades_paper.db') as db:
            db.executescript(_CREATE_TRADES+_CREATE_SHADOW_CANDIDATES)
            db.execute('''INSERT INTO trades(id,ticker,contract_symbol,option_type,strike,expiry,
                contracts,entry_price,entry_time,paper,strategy_id,broker_account_id,candidate_id,
                strategy_context_json,entry_order_id,entry_fill_time) VALUES
                (1,'SPY',?,'call',600,'2026-11-20',1,2,?,1,'test','a','candidate',?,'order',?)''',
                (C,T.isoformat(),json.dumps(meta),T.isoformat()))
            db.execute('''INSERT INTO shadow_candidates(candidate_id,observed_at,ticker,
                strategy_id,direction,confidence,broker_account_id,metadata_json,linked_trade_id)
                VALUES ('candidate',?,'SPY','test','bullish',1,'a',?,1)''',
                ((T-timedelta(seconds=20)).isoformat(),json.dumps(meta)))

    def test_original_entry_level_not_registry_metadata(self):
        self.original_entry()
        r=self.reader.entry_level(self.entry,'structural_levels.support')
        self.assertEqual(D(590),r['level'].value)
        self.assertTrue(r['level'].evidence_id.startswith('original_candidate:'))
        self.assertFalse(r['independently_reconciled_fill'])

    def test_raw_feature_requires_matching_original_level_evidence(self):
        import sqlite3
        self.original_entry(source_field='compression_low')
        strategy='V2_AFTERNOON_COMPRESSION_BREAKOUT'
        self.entry=replace(self.entry,scope=replace(self.entry.scope,strategy=strategy))
        with sqlite3.connect(self.root/'trades_paper.db') as db:
            meta=json.loads(db.execute('SELECT strategy_context_json FROM trades').fetchone()[0])
            meta['compression_low']=590
            db.execute('UPDATE trades SET strategy_id=?,strategy_context_json=?',(strategy,json.dumps(meta)))
            db.execute('UPDATE shadow_candidates SET strategy_id=?,metadata_json=?',(strategy,json.dumps(meta)))
        result=self.reader.entry_level(self.entry,'compression_low')
        self.assertEqual(D(590),result['level'].value)
        with sqlite3.connect(self.root/'trades_paper.db') as db:
            meta['compression_low']=589
            db.execute('UPDATE shadow_candidates SET metadata_json=?',(json.dumps(meta),))
        with self.assertRaisesRegex(ValueError,'raw_level_evidence_mismatch'):
            self.reader.entry_level(self.entry,'compression_low')

    def test_raw_feature_without_original_capture_is_not_reconstructed(self):
        import sqlite3
        self.original_entry()
        strategy='V2_AFTERNOON_COMPRESSION_BREAKOUT'
        self.entry=replace(self.entry,scope=replace(self.entry.scope,strategy=strategy))
        with sqlite3.connect(self.root/'trades_paper.db') as db:
            meta=json.loads(db.execute('SELECT strategy_context_json FROM trades').fetchone()[0])
            meta['compression_low']=590
            db.execute('UPDATE trades SET strategy_id=?,strategy_context_json=?',(strategy,json.dumps(meta)))
            db.execute('UPDATE shadow_candidates SET strategy_id=?,metadata_json=?',(strategy,json.dumps(meta)))
        with self.assertRaisesRegex(ValueError,'raw_level_evidence_mismatch'):
            self.reader.entry_level(self.entry,'compression_low')

    def test_late_level_blocked(self):
        self.original_entry(recorded_at=(T+timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError,'availability_not_proven'):
            self.reader.entry_level(self.entry,'structural_levels.support')

    def test_original_level_changed_in_trade_blocked(self):
        import sqlite3
        self.original_entry()
        with sqlite3.connect(self.root/'trades_paper.db') as db:
            meta=json.loads(db.execute('SELECT strategy_context_json FROM trades').fetchone()[0])
            meta['structural_levels']['support']=599
            db.execute('UPDATE trades SET strategy_context_json=?',(json.dumps(meta),))
        with self.assertRaisesRegex(ValueError,'context_mismatch'):
            self.reader.entry_level(self.entry,'structural_levels.support')

    def test_unmapped_raw_level_not_inferred(self):
        with self.assertRaisesRegex(ValueError,'missing_level_availability_schema'):
            self.reader.entry_level(self.entry,'or_low')

    def test_bytes_bounded_and_no_partial_success(self):
        self.record(); self.reader=ExitArchiveReader(self.root,max_bytes=1)
        with self.assertRaisesRegex(ValueError,'byte_limit'): self.read()

    def stock_archive(self, **changes):
        archive=Archive(self.root/'session_capture'); self.addCleanup(archive.db.close)
        quote=dict(symbol='SPY',last=600,trade_date=int(T.timestamp()*1000),volume=100)
        quote.update(changes)
        with archive.db:
            archive.record('2026-11-09','stock_quotes','*',{'symbols':['SPY']},T,T,
                           {'quotes':{'quote':quote}})
        return archive

    def test_stock_source_times_and_original_receipts(self):
        self.stock_archive()
        r=self.reader.stock_prints('SPY',T,T,source=SOURCE)
        self.assertEqual(1,len(r['prints'])); self.assertEqual(T,r['prints'][0].source_at)
        self.assertEqual(T,r['prints'][0].received_at)
        self.assertFalse(r['coverage_verified'])

    def test_stock_missing_source_time_is_not_repaired(self):
        self.stock_archive(trade_date=None)
        r=self.reader.stock_prints('SPY',T,T,source=SOURCE)
        self.assertEqual([],r['prints']); self.assertEqual(1,len(r['rejected']))

    def test_stock_wrong_feed_and_recovery_rejected(self):
        archive=self.stock_archive()
        self.assertEqual([],self.reader.stock_prints('SPY',T,T,source='iex')['prints'])
        with archive.db: archive.db.execute("UPDATE responses SET provenance='provider_history_received_later'")
        self.assertEqual([],self.reader.stock_prints('SPY',T,T,source=SOURCE)['prints'])

    def test_stock_missing_ticker_reported(self):
        self.stock_archive()
        r=self.reader.stock_prints('QQQ',T,T,source=SOURCE)
        self.assertEqual('missing_or_duplicate_ticker',r['rejected'][0]['reason'])
