"""Bounded read-only adapters. Stored observations are not confirmed fills.

This module does not certify decision coverage or entry-level availability.
It never creates archives, enrolls experiments, or imports execution clients.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zlib
from zoneinfo import ZoneInfo

from strategy_health.paired_exit_accounting import Quote, clock, money
from strategy_health.structural_supplement import StockPrint, level_from_context
from strategy_health.native_exit_requests import context_hash


def timestamp(value):
    return clock(datetime.fromisoformat(value)).astimezone(timezone.utc)


def journal_fill_timestamp(value):
    """Decode trades.entry_fill_time's documented Eastern-naive schema only.

    Provider clocks and candidate timestamps still require explicit offsets.
    Never silently select one side of a daylight-saving ambiguity.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return timestamp(value)
    zone = ZoneInfo('America/New_York')
    candidates = set()
    for fold in (0, 1):
        local = parsed.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == parsed:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError('ambiguous_or_nonexistent_journal_fill_time')
    return candidates.pop()


def source_timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError('missing_source_timestamp')
    return datetime.fromtimestamp(value / 1000, timezone.utc)


class ExitArchiveReader:
    def __init__(self, user_root, *, max_rows=100000, timeout_seconds=5, max_bytes=64*1024*1024):
        self.root = Path(user_root).resolve()
        if not isinstance(max_rows, int) or not 1 <= max_rows <= 1000000:
            raise ValueError('invalid_row_limit')
        if not 0 < timeout_seconds <= 30:
            raise ValueError('invalid_query_timeout')
        if not isinstance(max_bytes,int) or not 1 <= max_bytes <= 256*1024*1024:
            raise ValueError('invalid_byte_limit')
        self.max_rows = max_rows
        self.timeout = timeout_seconds
        self.max_bytes = max_bytes

    @contextmanager
    def _open(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('archive_outside_user_root')
        if not path.is_file():
            raise ValueError('missing_archive:' + relative)
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.2)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + self.timeout
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            yield db
        finally:
            db.close()

    def _rows(self, db, sql, params):
        rows=[]; size=0
        for row in db.execute(sql + ' LIMIT ?', (*params, self.max_rows + 1)):
            if len(rows) >= self.max_rows:
                raise ValueError('archive_row_limit_exceeded')
            size += sum(len(v.encode('utf-8')) if isinstance(v,str) else len(v)
                        if isinstance(v,bytes) else 8 for v in row)
            if size > self.max_bytes: raise ValueError('archive_byte_limit_exceeded')
            rows.append(row)
        return rows

    def entry_level(self, entry, field):
        """Read original linked candidate evidence, never later registry copies.

        Require original structural_levels source and recording clocks. Raw
        feature fields additionally require a matching captured source_field,
        strategy mapping and value. Never infer availability for older records.
        """
        entry.scope.validate(); clock(entry.filled_at)
        from strategy_health.structural_capture import LEVEL_FIELDS
        raw_fields = LEVEL_FIELDS.get(entry.scope.strategy, ())
        raw_field = field in raw_fields and field is not None
        if field not in ('structural_levels.support','structural_levels.resistance') and not raw_field:
            raise ValueError('missing_level_availability_schema:'+field)
        with self._open('trades_'+entry.scope.mode+'.db') as db:
            trades=self._rows(db,'SELECT * FROM trades WHERE id=?',(str(entry.trade_id),))
            if len(trades)!=1: raise ValueError('missing_original_trade')
            trade=trades[0]
            if (trade['broker_account_id']!=entry.scope.account
                    or trade['paper']!=int(entry.scope.mode=='paper')
                    or trade['strategy_id']!=entry.scope.strategy
                    or trade['ticker']!=entry.scope.ticker
                    or trade['contract_symbol']!=entry.contract):
                raise ValueError('entry_trade_scope_mismatch')
            if (not trade['entry_order_id'] or not trade['entry_fill_time']
                    or journal_fill_timestamp(trade['entry_fill_time'])!=entry.filled_at
                    or money(trade['entry_price'])!=money(entry.premium)):
                raise ValueError('entry_fill_record_mismatch')
            context=json.loads(trade['strategy_context_json'] or '{}')
            if context.get('strategy_version')!=entry.scope.version:
                raise ValueError('entry_version_mismatch')
            candidates=self._rows(db,'SELECT * FROM shadow_candidates WHERE candidate_id=?',
                                  (trade['candidate_id'],))
            if len(candidates)!=1: raise ValueError('missing_original_candidate')
            candidate=candidates[0]
            if (candidate['broker_account_id']!=entry.scope.account
                    or candidate['ticker']!=entry.scope.ticker
                    or candidate['strategy_id']!=entry.scope.strategy
                    or str(candidate['linked_trade_id'])!=str(entry.trade_id)):
                raise ValueError('candidate_trade_link_mismatch')
            observed=timestamp(candidate['observed_at'])
            metadata=json.loads(candidate['metadata_json'] or '{}')
        if metadata.get('strategy_version')!=entry.scope.version:
            raise ValueError('candidate_version_mismatch')
        levels=metadata.get('structural_levels')
        if not isinstance(levels,dict) or levels.get('schema')!=1 or levels.get('status')!='captured':
            raise ValueError('missing_original_structural_levels')
        if levels!=context.get('structural_levels'):
            raise ValueError('entry_level_context_mismatch')
        if levels.get('updates_after_entry') is not False:
            raise ValueError('entry_level_not_frozen')
        completed=timestamp(levels.get('source_completed_at'))
        recorded=timestamp(levels.get('recorded_at'))
        if not completed<=recorded<=observed<=entry.filled_at:
            raise ValueError('entry_level_availability_not_proven')
        level_key = field.split('.')[-1]
        if raw_field:
            level_key = 'support' if raw_fields[0] == field else 'resistance'
            if (levels.get('source_field') != field or metadata.get(field) != context.get(field)
                    or metadata.get(field) != levels.get(level_key)):
                raise ValueError('entry_raw_level_evidence_mismatch')
        if money(levels.get(level_key))<=0:
            raise ValueError('invalid_entry_level')
        digest=hashlib.sha256(json.dumps(metadata,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        evidence='original_candidate:'+str(candidate['candidate_id'])+':'+digest
        level=level_from_context(entry,metadata,field,source_completed_at=completed,
                                 recorded_at=recorded,evidence_id=evidence)
        return dict(level=level, frozen_context_hash=context_hash(context),
                    candidate_observed_at=observed,entry_order_id=trade['entry_order_id'],
                    entry_fill_time_raw=trade['entry_fill_time'],
                    entry_fill_time_schema='trades_eastern_naive_or_explicit_offset',
                    independently_reconciled_fill=False)

    def option_quotes(self, entry, registration_id, through):
        """Read only observations linked to this exact broker-trade registration.

        Rejected observations remain listed with their IDs. Caller must apply
        frozen freshness/coverage rules; this result alone is not evaluable.
        """
        entry.scope.validate(); clock(entry.filled_at); clock(through)
        if through < entry.filled_at:
            raise ValueError('invalid_capture_window')
        with self._open('fast_capture/fast_capture.sqlite3') as db:
            reg = db.execute('SELECT * FROM registrations WHERE id=?', (registration_id,)).fetchone()
            if reg is None:
                raise ValueError('missing_registration')
            expected = dict(account=entry.scope.account, mode=entry.scope.mode,
                            strategy=entry.scope.strategy, ticker=entry.scope.ticker,
                            version=entry.scope.version, symbol=entry.contract,
                            origin='broker_trade', origin_id=str(entry.trade_id))
            if any(reg[k] != v for k, v in expected.items()):
                raise ValueError('registration_scope_mismatch')
            if timestamp(reg['entry_at']) != entry.filled_at:
                raise ValueError('registration_entry_time_mismatch')
            rows = self._rows(db, '''SELECT o.* FROM links l JOIN observations o
                ON o.symbol=l.symbol AND o.received_at=l.received_at
                WHERE l.registration=? AND o.symbol=?
                AND julianday(o.received_at)>=julianday(?)
                AND julianday(o.received_at)<=julianday(?) ORDER BY julianday(o.received_at)''',
                (registration_id, entry.contract, entry.filled_at.isoformat(), through.isoformat()))
        quotes, rejected, provenance = [], [], []
        for row in rows:
            identity = hashlib.sha256((row['symbol'] + row['received_at'] + row['payload']).encode()).hexdigest()
            evidence = 'fast_capture:' + identity
            try:
                raw = json.loads(row['payload'])
                if raw.get('symbol') != entry.contract:
                    raise ValueError('payload_contract_mismatch')
                received = timestamp(row['received_at']); requested = timestamp(row['requested_at'])
                if requested > received:
                    raise ValueError('request_after_receipt')
                size = raw.get('bidsize')
                if isinstance(size, bool) or not isinstance(size, int) or size < 1:
                    raise ValueError('missing_valid_bid_size')
                quotes.append(Quote(entry.contract, received, source_timestamp(raw.get('bid_date')),
                    source_timestamp(raw.get('ask_date')), money(raw.get('bid')), money(raw.get('ask')),
                    size, evidence))
                provenance.append(dict(evidence_id=evidence, requested_at=requested,
                    capture_validation=row['validation'], producer='fast_capture',
                    kind='forward_option_snapshot_not_fill'))
            except (ValueError, TypeError, AttributeError, OverflowError, OSError) as exc:
                rejected.append(dict(evidence_id=evidence, reason=str(exc)))
        return dict(quotes=quotes, rejected=rejected, provenance=provenance,
                    registration_id=registration_id, policy=reg['policy'],
                    coverage_verified=False, entry_levels_verified=False)

    def decision_events(self, entry, through):
        entry.scope.validate(); clock(entry.filled_at); clock(through)
        if through < entry.filled_at:
            raise ValueError('invalid_capture_window')
        with self._open('exit_decisions/decisions.sqlite3') as db:
            rows = self._rows(db, '''SELECT * FROM decisions WHERE account=? AND mode=?
                AND trade_id=? AND strategy=? AND ticker=?
                AND julianday(recorded_at)>=julianday(?) AND julianday(recorded_at)<=julianday(?)
                ORDER BY julianday(recorded_at),event_id''',
                (entry.scope.account, entry.scope.mode, str(entry.trade_id), entry.scope.strategy,
                 entry.scope.ticker, entry.filled_at.isoformat(), through.isoformat()))
        events = []
        for row in rows:
            event = json.loads(row['payload']); trade = event.get('trade', {})
            if (event.get('event_id') != row['event_id'] or event.get('mode') != row['mode']
                    or timestamp(event.get('recorded_at')) != timestamp(row['recorded_at'])
                    or str(trade.get('id')) != str(entry.trade_id)
                    or trade.get('broker_account_id') != entry.scope.account
                    or trade.get('strategy_id') != entry.scope.strategy
                    or trade.get('ticker') != entry.scope.ticker
                    or trade.get('contract_symbol') != entry.contract):
                raise ValueError('decision_payload_identity_mismatch')
            context = trade.get('strategy_context_json')
            if isinstance(context, str): context = json.loads(context)
            if not isinstance(context, dict) or context.get('strategy_version') != entry.scope.version:
                raise ValueError('decision_version_mismatch')
            events.append(event)
        return dict(events=events, decision_coverage_verified=False)

    def stock_prints(self, ticker, start, through, *, source):
        """Observed last trades, not an exchange-complete print stream.

        Fingerprints deduplicate snapshots; they are not exchange sequence IDs.
        Recovered bars cannot enter this forward-observation adapter.
        """
        clock(start); clock(through)
        if not ticker or not source or through < start:
            raise ValueError('invalid_stock_window_or_source')
        with self._open('session_capture/session_capture.sqlite3') as db:
            rows = self._rows(db, '''SELECT * FROM responses WHERE kind='stock_quotes'
                AND ticker='*' AND julianday(received_at)>=julianday(?)
                AND julianday(received_at)<=julianday(?) ORDER BY julianday(received_at),id''',
                (start.isoformat(), through.isoformat()))
        prints, rejected = [], []
        for row in rows:
            evidence = 'session_capture:' + row['id'] + ':' + ticker
            try:
                if row['source'] != source or row['provenance'] != 'forward_snapshot':
                    raise ValueError('wrong_source_or_not_forward_observed')
                received = timestamp(row['received_at'])
                if timestamp(row['requested_at']) > received:
                    raise ValueError('request_after_receipt')
                decoder = zlib.decompressobj()
                raw = decoder.decompress(row['payload'], 4000001)
                if len(raw) > 4000000 or not decoder.eof or decoder.unused_data:
                    raise ValueError('payload_limit_or_invalid_compression')
                payload = json.loads(raw)
                quotes = (payload.get('quotes') or {}).get('quote')
                if isinstance(quotes, dict): quotes = [quotes]
                matches = [q for q in (quotes or []) if isinstance(q,dict) and q.get('symbol') == ticker]
                if len(matches) != 1:
                    raise ValueError('missing_or_duplicate_ticker')
                q = matches[0]
                source_at = source_timestamp(q.get('trade_date')); price = money(q.get('last'))
                if price <= 0: raise ValueError('invalid_stock_price')
                fingerprint = hashlib.sha256(json.dumps([ticker,q['trade_date'],str(price),q.get('volume')]).encode()).hexdigest()
                prints.append(StockPrint(ticker,price,source_at,received,'snapshot_fingerprint:'+fingerprint,
                                         evidence,source,'forward_observed'))
            except (ValueError, TypeError, AttributeError, OverflowError, OSError, zlib.error) as exc:
                rejected.append(dict(evidence_id=evidence,reason=str(exc)))
        return dict(prints=prints,rejected=rejected,coverage_verified=False,
                    source_event_identity='snapshot_fingerprint_not_exchange_sequence')
