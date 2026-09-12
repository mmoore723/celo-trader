"""Frozen affordable-contract diagnostic, retaining native Displacement clocks.

Candidate changes only the premium band to $0.80-$1.42. Keep 0-7 DTE calls,
OTM, <=8% spread, first eight expiries and the original closest-to-$2 ranking.
Keep both the existing structural exit and timer control. No parameter search.
Stream existing archives in memory; retain original/candidate paths and never
substitute missing prices. This seven-setup development cohort is not a holdout.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from zipfile import ZipFile

import databento_dbn as dbn
import pandas as pd
import zstandard

from research.jobs.replay_spy_affordable_contracts import checkpoint, digest, moment, quote

PROTOCOL = 'displacement_native_fixed080_142_contract_comparison_v1'
COLUMNS = ['ts_recv', 'rtype', 'symbol', 'bid_px_00', 'ask_px_00', 'bid_sz_00', 'ask_sz_00']


class HashedReader:
    def __init__(self, source):
        self.source, self.digest = source, hashlib.sha256()

    def read(self, size=-1):
        data = self.source.read(size)
        self.digest.update(data)
        return data


def csv_groups(stream):
    pending, previous = None, None
    with zstandard.ZstdDecompressor().stream_reader(stream) as decoder:
        for chunk in pd.read_csv(decoder, usecols=COLUMNS, dtype=str, keep_default_na=False, chunksize=100000):
            stamps = chunk['ts_recv']
            if not stamps.is_monotonic_increasing or previous and stamps.iloc[0] < previous:
                raise ValueError('Unordered availability clock')
            if not (chunk['rtype'] == '193').all():
                raise ValueError('Wrong CSV schema')
            previous = stamps.iloc[-1]
            both = pd.concat([pending, chunk], ignore_index=True) if pending is not None else chunk
            for stamp, group in both[both['ts_recv'] != previous].groupby('ts_recv', sort=False):
                yield moment(stamp), group
            pending = both[both['ts_recv'] == previous].copy()
        if pending is not None:
            yield moment(previous), pending


def dbn_groups(stream):
    decoder = dbn.DBNDecoder(compression=dbn.Compression.ZSTD)
    mappings, current, rows = None, None, []
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        for record in decoder.write_and_decode(chunk):
            if isinstance(record, dbn.Metadata):
                if mappings is not None or record.schema != 'cbbo-1m' or str(record.stype_out) != 'instrument_id':
                    raise ValueError('Wrong DBN metadata')
                mappings = defaultdict(list)
                for symbol, intervals in record.mappings.items():
                    for i in intervals:
                        mappings[int(i['symbol'])].append((i['start_date'], i['end_date'], symbol))
                continue
            if mappings is None or not isinstance(record, dbn.CBBOMsg) or int(record.rtype) != 193:
                raise ValueError('Wrong DBN record')
            if record.ts_recv == dbn.UNDEF_TIMESTAMP or record.ts_recv % 60000000000:
                raise ValueError('Missing or non-minute availability')
            now = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=record.ts_recv//1000000000)
            if current and now < current:
                raise ValueError('Unordered DBN availability')
            if current is not None and now != current:
                yield current, pd.DataFrame(rows)
                rows = []
            current = now
            symbols = {s for start, end, s in mappings.get(record.instrument_id, []) if start <= now.date() < end}
            if len(symbols) != 1:
                raise ValueError('Missing or ambiguous dated OCC mapping')
            level = record.levels[0]
            rows.append(dict(ts_recv=now.isoformat(), rtype='193', symbol=next(iter(symbols)),
                bid_px_00=str(D(level.bid_px)/D(dbn.FIXED_PRICE_SCALE)),
                ask_px_00=str(D(level.ask_px)/D(dbn.FIXED_PRICE_SCALE)),
                bid_sz_00=str(level.bid_sz), ask_sz_00=str(level.ask_sz)))
    if mappings is None or decoder.buffer():
        raise ValueError('Truncated DBN input')
    if rows:
        yield current, pd.DataFrame(rows)


@lru_cache(maxsize=50000)
def identity(symbol, ticker):
    match = re.fullmatch(re.escape(ticker)+r'\s+(\d{6})([CP])(\d{8})', symbol.strip())
    if not match:
        return None
    return datetime.strptime(match[1], '%y%m%d').date(), match[2], D(match[3])/1000


def choose(entry, raw_rows, now):
    parsed = [(raw, identity(raw['symbol'], entry['ticker'])) for raw in raw_rows]
    expiries = sorted({p[0] for _, p in parsed if p and 0 <= (p[0]-now.date()).days <= 7})[:8]
    pools = {'control': {}, 'candidate': {}}
    spot = D(str(entry['stock_reference']))
    for raw, p in parsed:
        if not p or p[0] not in expiries or p[1] != 'C' or p[2] <= spot:
            continue
        q = quote(raw, now)
        if q is None:
            continue
        ask, bid = D(q['ask']), D(q['bid'])
        spread = (ask-bid)/((ask+bid)/2)
        if spread > D('.08'):
            continue
        key = (abs(ask-D(2)), abs(p[2]-spot), p[0], spread, q['contract'])
        for name, low, high in [('control', D('1.50'), D('2.50')), ('candidate', D('.80'), D('1.42'))]:
            if low <= ask <= high:
                prior = pools[name].get(q['contract'])
                if prior and prior != (key, q):
                    raise ValueError('Conflicting entry quote')
                pools[name][q['contract']] = key, q
    return {name: min(pool.values(), key=lambda x:x[0])[1] if pool else None for name, pool in pools.items()}


def price_day(entries, groups):
    states = {r['candidate_id']: dict(source=r, paths={'control': [], 'candidate': []}, selections=None) for r in entries}
    for now, group in groups:
        active = [s for s in states.values() if moment(s['source']['entry_snapshot_at']) <= now <= max(
            moment(s['source']['legs'][leg]['quote_at']) for leg in ('structural', 'timer'))]
        if not active:
            continue
        for state in active:
            if now == moment(state['source']['entry_snapshot_at']):
                state['selections'] = choose(state['source'], group.to_dict('records'), now)
        wanted = {q['contract'] for s in active if s['selections'] for q in s['selections'].values() if q}
        book = {}
        for raw in group[group['symbol'].str.strip().isin(wanted)].to_dict('records'):
            q = quote(raw, now)
            if q:
                if q['contract'] in book and book[q['contract']] != q:
                    raise ValueError('Conflicting path quote')
                book[q['contract']] = q
        for state in active:
            for name, q in (state['selections'] or {}).items():
                if q and q['contract'] in book:
                    state['paths'][name].append(book[q['contract']])
    results = []
    for state in states.values():
        source = state['source']
        if state['selections'] is None:
            raise ValueError('Missing original entry snapshot')
        control = state['selections']['control']
        if not control or control['contract'] != source['contract'].strip() or any(
                D(control[k]) != D(source['entry_'+k]) for k in ('bid', 'ask')):
            raise ValueError('Original ranked contract or entry price not reproduced')
        result = dict(id=source['candidate_id'], ticker=source['ticker'], entry_time=source['entry_snapshot_at'],
                      paths=state['paths'], selections=state['selections'], legs={})
        for name, initial in state['selections'].items():
            result['legs'][name] = {}
            for leg, old in source['legs'].items():
                exit_quote = next((q for q in state['paths'][name] if moment(q['time']) == moment(old['quote_at'])), None)
                priced = dict(status='no_contract' if initial is None else 'missing_exit', exit_time=old['quote_at'])
                if initial and exit_quote:
                    net = (D(exit_quote['bid'])-D(initial['ask']))*100-D('3.30')
                    priced.update(status='priced', exit_bid=exit_quote['bid'], net=str(net))
                if name == 'control' and (priced['status'] != 'priced' or D(priced['exit_bid']) != D(old['exit_bid']) or
                        D(priced['net']) != D(str(old['net_pnl_one_contract']))):
                    raise ValueError('Original exit or costs not reproduced')
                result['legs'][name][leg] = priced
        results.append(result)
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('reports', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Preserve existing output; inspect any prior running process before resuming')
    assessment = args.reports/'displacement_recovered_complete_assessment_2026-09-11.json'
    baseline = json.loads(assessment.read_text())
    entries = [r for r in baseline['rows'] if r['profile']=='reviewed_bounds' and r['native'] and r['independent']]
    if len(entries) != 7 or len({r['candidate_id'] for r in entries}) != 7:
        raise ValueError('Native cohort changed')
    result = dict(protocol=PROTOCOL, input_sha256=digest(assessment), code_sha256=digest(Path(__file__)),
                  helper_sha256=digest(Path(__file__).with_name('replay_spy_affordable_contracts.py')),
                  complete=False, rows=[], member_sha256={}, archives={}, processed=[])
    checkpoint(args.output, result)
    for ticker in ('TSLA', 'AMZN'):
        old = json.loads((args.reports/f'displacement_{ticker.lower()}_corrected_prices_2026-09-11.json').read_text())
        archive = Path(old['archive'])
        if digest(archive) != old['archive_sha256']:
            raise ValueError('Archive changed')
        result['archives'][ticker] = dict(path=str(archive), sha256=old['archive_sha256'])
        by_day = defaultdict(list)
        for r in entries:
            if r['ticker'] == ticker:
                by_day[r['date']].append(r)
        with ZipFile(archive) as z:
            query = json.loads(z.read('metadata.json'))['query']
            if query['schema'] != 'cbbo-1m' or query['symbols'] != [ticker+'.OPT'] or query['encoding'] not in ('csv', 'dbn'):
                raise ValueError('Wrong archive metadata')
            for day in sorted(by_day):
                if shutil.disk_usage(args.output.parent).free < 2*1024**3:
                    raise ValueError('Disk reserve reached')
                matches = [n for n in z.namelist() if re.search(day.replace('-','')+r'\.cbbo-1m\.', n)]
                if len(matches) != 1:
                    raise ValueError('Missing or duplicate date member')
                with z.open(matches[0]) as source:
                    hashed = HashedReader(source)
                    groups = csv_groups(hashed) if query['encoding']=='csv' else dbn_groups(hashed)
                    priced = price_day(by_day[day], groups)
                if hashed.digest.hexdigest() != old['member_sha256'][day]:
                    raise ValueError('Source member changed')
                result['rows'].extend(priced)
                result['member_sha256'][ticker+'|'+day] = hashed.digest.hexdigest()
                result['processed'].append(ticker+'|'+day)
                checkpoint(args.output, result)
                print(f'Priced {len(result["rows"])}/7 native setups: {ticker} {day}', flush=True)
    result['complete'] = True
    checkpoint(args.output, result)


if __name__ == '__main__':
    main()
