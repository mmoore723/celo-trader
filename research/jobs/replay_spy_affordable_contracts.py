"""Frozen $1.42 ask-cap experiment on three enabled SPY strategies.

No parameter sweep, downloads, broker calls or production wiring. Keep each
baseline signal and entry clock, OTM direction, first three 7-21 DTE expiries,
8% spread ceiling and 30-minute exit. Rank eligible contracts by expiry, strike
distance, spread and symbol, as production does. Only add the ask ceiling.
The $1.42 ceiling is the audited $5k/3% risk tier after its 5% entry reserve.
This fixed initial-cap diagnostic is NOT a dynamic whole-account simulation.

Stream each existing day once in timestamp order. Retain source paths only for
the original and candidate contracts. Missing contracts/fills stay explicit.
Costs match prior baselines ($3.30 roundtrip per contract), not actual invoices.
"""
import argparse
from collections import defaultdict
from datetime import datetime,timedelta
from decimal import Decimal as D
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import pandas as pd
import zstandard
from research.engine.providers.databento import _parse_symbol

PROTOCOL='spy_three_strategies_affordability_fixed142_v1'
CAP=D('1.42')
COLUMNS=['ts_recv','rtype','symbol','bid_px_00','ask_px_00','bid_sz_00','ask_sz_00']
SOURCES={
    'V2_SPY_TREND_CONT':('spy_trend_corrected_clock_baseline_2026-09-11.json',
                        'spy_trend_cbbo_interval_end_30m_research_v1'),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION':('failed_range_corrected_clock_baseline_2026-09-11.json',
                                      'failed_range_two_contract_profiles_interval_end_30m_v1'),
    'V2_SPY_AFTERNOON_FVG':('fvg_corrected_clock_baseline_2026-09-11.json',
                          'spy_afternoon_fvg_two_profiles_corrected_clock_30m_v1')}


def moment(text):
    t=datetime.fromisoformat(text.replace('Z','+00:00'))
    if t.tzinfo is None or t.second or t.microsecond:
        raise ValueError('Expected timezone-aware minute-end availability')
    return t


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def snapshots(path):
    """Yield complete timestamp groups, including groups split across chunks."""
    pending=None
    previous=None
    with path.open('rb') as raw,zstandard.ZstdDecompressor().stream_reader(raw) as decoder:
        for chunk in pd.read_csv(decoder,usecols=COLUMNS,dtype=str,keep_default_na=False,chunksize=100000):
            stamps=chunk['ts_recv']
            if not stamps.is_monotonic_increasing or (previous is not None and stamps.iloc[0]<previous):
                raise ValueError('Archive not ordered by availability time')
            previous=stamps.iloc[-1]
            if not (chunk['rtype']=='193').all():
                raise ValueError('Expected CBBO-1m')
            both=pd.concat([pending,chunk],ignore_index=True) if pending is not None else chunk
            complete=both[both['ts_recv']!=previous]
            for stamp,group in complete.groupby('ts_recv',sort=False):
                yield moment(stamp),group
            pending=both[both['ts_recv']==previous].copy()
        if pending is not None and not pending.empty:
            yield moment(previous),pending


@lru_cache(maxsize=50000)
def identity(symbol):
    return _parse_symbol(symbol,'SPY')


def quote(raw,now):
    try:
        bid,ask,bs,asz=(D(raw[k]) for k in ('bid_px_00','ask_px_00','bid_sz_00','ask_sz_00'))
        if not all(x.is_finite() for x in (bid,ask,bs,asz)) or not 0<bid<=ask<1000000 or min(bs,asz)<=0:
            return None
    except Exception:
        return None
    return dict(contract=raw['symbol'].strip(),time=now.isoformat(),bid=str(bid),ask=str(ask),
                bid_size=str(bs),ask_size=str(asz))


def choose(entry,rows,now):
    parsed=[(raw,identity(raw['symbol'])) for raw in rows]
    expiries=sorted({p[2] for _,p in parsed if p and 7<=(datetime.fromisoformat(p[2]).date()-now.date()).days<=21})[:3]
    eligible={}
    bullish=entry['direction']=='bullish'
    if entry['direction'] not in ('bullish','bearish'):
        raise ValueError('Unknown direction')
    spot=D(str(entry['stock_reference']))
    for raw,p in parsed:
        if not p or p[2] not in expiries or p[4]!=('call' if bullish else 'put'):
            continue
        strike=D(str(p[3]))
        if not (strike>spot if bullish else strike<spot):
            continue
        q=quote(raw,now)
        if q is None or not D('.80')<=D(q['ask'])<=CAP:
            continue
        spread=(D(q['ask'])-D(q['bid']))/((D(q['ask'])+D(q['bid']))/2)
        if spread>D('.08'):
            continue
        key=(p[2],abs(strike-spot),spread,p[0])
        prior=eligible.get(p[0])
        if prior and prior[1]!=q:
            raise ValueError('Conflicting entry quote')
        eligible[p[0]]=(key,q)
    return min(eligible.values(),key=lambda x:x[0])[1] if eligible else None


def finish(entry,path,initial):
    if initial is None:
        return dict(status='no_affordable_contract')
    start=moment(entry['entry_time']);wanted=start+timedelta(minutes=31)
    q=next((q for q in path if moment(q['time'])==wanted),None)
    if q is None:
        return dict(status='missing_exit',contract=initial['contract'],entry_ask=initial['ask'])
    return dict(status='priced',contract=initial['contract'],entry_time=start.isoformat(),
                entry_ask=initial['ask'],entry_bid=initial['bid'],exit_time=q['time'],exit_bid=q['bid'],
                net=str((D(q['bid'])-D(initial['ask']))*100-D('3.30')))


def day_replay(entries,path):
    states={e['id']:dict(entry=e,control_path=[],candidate_path=[],candidate=None,entry_seen=False) for e in entries}
    starts=defaultdict(list)
    for e in entries:
        starts[moment(e['entry_time'])].append(states[e['id']])
    for now,group in snapshots(path):
        active=[s for s in states.values() if moment(s['entry']['entry_time'])<=now<=moment(s['entry']['exit_time'])]
        if not active:
            continue
        if now in starts:
            raw_rows=group.to_dict('records')
            for state in starts[now]:
                state['entry_seen']=True
                state['candidate']=choose(state['entry'],raw_rows,now)
        wanted={s['entry']['contract'] for s in active}
        wanted.update(s['candidate']['contract'] for s in active if s['candidate'])
        selected=group[group['symbol'].str.strip().isin(wanted)]
        book={}
        for raw in selected.to_dict('records'):
            q=quote(raw,now)
            if q:
                if q['contract'] in book and book[q['contract']]!=q:
                    raise ValueError('Conflicting snapshot')
                book[q['contract']]=q
        for state in active:
            for name,symbol in [('control',state['entry']['contract']),
                                ('candidate',state['candidate']['contract'] if state['candidate'] else None)]:
                if symbol in book:
                    state[name+'_path'].append(book[symbol])
    output=[]
    for e in entries:
        s=states[e['id']]
        if not s['entry_seen']:
            raise ValueError('Entry snapshot absent from source')
        first=next((q for q in s['control_path'] if moment(q['time'])==moment(e['entry_time'])),None)
        if first is None or any(D(first[k])!=D(str(e['entry_'+k])) for k in ('bid','ask')):
            raise ValueError('Original entry not reproduced')
        control=finish(e,s['control_path'],first)
        if (control['status']!='priced' or D(control['exit_bid'])!=D(str(e['exit_bid']))
                or abs(D(control['net'])-D(str(e['net_pnl_one_contract'])))>D('.000002')):
            raise ValueError('Original exit/costs not reproduced')
        output.append(dict(id=e['id'],strategy_id=e['strategy_id'],date=e['date'],
            independent=e['independent'],control=control,candidate=finish(e,s['candidate_path'],s['candidate']),
            control_fits_initial_budget=D(first['ask'])<=CAP,
            control_path=s['control_path'],candidate_path=s['candidate_path']))
    return output


def checkpoint(path,data):
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    with os.fdopen(fd,'w') as out:
        json.dump(data,out,indent=2);out.flush();os.fsync(out.fileno())
    os.replace(name,path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baselines','archive','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();entries=[];hashes={};members={}
    for sid,(filename,protocol) in SOURCES.items():
        source=args.baselines/filename;d=json.loads(source.read_text());hashes[sid]=digest(source)
        if not d['complete'] or d['protocol']!=protocol or d['archive']!=str(args.archive.resolve()):
            raise ValueError('Wrong baseline/archive')
        for day,value in d['member_sha256'].items():
            if day in members and members[day]!=value:
                raise ValueError('Conflicting archive hash')
            members[day]=value
        for row in d['rows']:
            if row.get('profile','reviewed_bounds')!='reviewed_bounds':continue
            if sid=='V2_FAILED_OR_BREAK_VWAP_REVERSION' and not row['native']:continue
            if row['status']!='priced':raise ValueError('Unexpected source status')
            if moment(row['exit_time'])-moment(row['entry_time'])!=timedelta(minutes=31):
                raise ValueError('Wrong baseline hold')
            entries.append(dict(row,strategy_id=sid,id=sid+'|'+row['candidate_id']))
    if len({e['id'] for e in entries})!=len(entries):raise ValueError('Duplicate candidate')
    by_day=defaultdict(list)
    for entry in entries:by_day[entry['date']].append(entry)
    fixed=dict(protocol=PROTOCOL,baseline_sha256=hashes,code_sha256=digest(Path(__file__)),
               symbol_parser_sha256=digest(Path(__file__).parents[1]/'engine/providers/databento.py'),
               maximum_ask=str(CAP),initial_account=5000,entry_risk_fraction='.03',entry_reserve_fraction='.05')
    result=json.loads(args.output.read_text()) if args.output.exists() else dict(**fixed,rows=[],processed_dates=[],complete=False)
    if any(result.get(k)!=v for k,v in fixed.items()):raise ValueError('Checkpoint identity differs')
    days=sorted(by_day)
    if result['processed_dates']!=days[:len(result['processed_dates'])]:raise ValueError('Invalid checkpoint dates')
    expected=[e['id'] for day in result['processed_dates'] for e in by_day[day]]
    if [r['id'] for r in result['rows']]!=expected:raise ValueError('Invalid checkpoint rows')
    for day in days[len(result['processed_dates']):]:
        if shutil.disk_usage(args.output.parent).free<2*1024**3:raise ValueError('Disk reserve too low')
        path=args.archive/f'opra-pillar-{day.replace("-", "")}.cbbo-1m.csv.zst'
        if digest(path)!=members[day]:raise ValueError('Changed archive member')
        result['rows'].extend(day_replay(by_day[day],path))
        result['processed_dates'].append(day);result['complete']=len(result['processed_dates'])==len(days)
        checkpoint(args.output,result)
        print(f'{len(result["processed_dates"])}/{len(days)} dates; {len(result["rows"])}/{len(entries)} entries',flush=True)


if __name__=='__main__':main()
