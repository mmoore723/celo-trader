"""One frozen 20% initial-loss experiment; sampled quotes, no order authority.

Streams original compressed CSV, retaining only the selected contract's small
path for independent verification. Uses interval-end ts_recv, never ts_event.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
from statistics import median
from zipfile import ZipFile

import zstandard

PROTOCOL = 'two_leg_exact_decimal_initial_loss20_90m_v1'
D = Decimal


def number(value):
    n = D(str(value))
    if not n.is_finite():
        raise ValueError('Nonfinite price')
    return n


def at(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone required')
    return t


def usable(q):
    bid, ask = number(q['bid']), number(q['ask'])
    return 0 < bid <= ask < 1000000 and number(q['bid_size']) > 0 and number(q['ask_size']) > 0


def leg(decision, path, reason):
    found = next((q for q in path if decision < at(q['time']) <= decision+timedelta(seconds=60)), None)
    result = {'status': 'missing_quote', 'decision_at': decision.isoformat(), 'reason': reason}
    if found:
        result.update(status='priced', bid=found['bid'], exit_time=found['time'])
    return result


def replay(entry, snapshots):
    start = at(entry['entry_time'])
    cap = start + timedelta(minutes=90)
    ask = number(entry['entry_ask'])
    if not 0 < number(entry['entry_bid']) <= ask:
        raise ValueError('Invalid entry')
    unique = {}
    for q in snapshots:
        if q['contract'] != entry['contract'] or not start <= at(q['time']) <= cap+timedelta(seconds=60):
            continue
        if not usable(q):
            continue
        t = at(q['time'])
        if t in unique and unique[t] != q:
            raise ValueError('Conflicting duplicate snapshot')
        unique[t] = q
    initial = unique.get(start)
    if not initial or number(initial['bid']) != number(entry['entry_bid']) or number(initial['ask']) != ask:
        raise ValueError('Entry quote does not reproduce baseline')
    path = [q for t,q in sorted(unique.items()) if t>start]
    control = leg(cap, path, 'fixed_90m')
    if entry['status'] == 'priced':
        if (control['status'] != 'priced' or number(control['bid']) != number(entry['exit_bid'])
                or at(control['exit_time']) != at(entry['exit_time'])):
            raise ValueError('Control does not reproduce baseline')
        expected = (number(entry['exit_bid'])-ask)*100-D('3.30')
        if abs(number(entry['net_pnl_one_contract'])-expected) > D('.000002'):
            raise ValueError('Baseline cost arithmetic differs')
    elif entry['status'] != 'missing_exit' or control['status'] != 'missing_quote':
        raise ValueError('Baseline missingness differs')
    previous = start
    variant = None
    floor = ask*D('.80')
    for q in path:
        t = at(q['time'])
        if min(t,cap)-previous > timedelta(seconds=120):
            variant = {'status': 'missing_path', 'reason': 'quote_gap_over_120s'}
            break
        if t >= cap:
            break
        previous = t
        if number(q['bid']) <= floor:
            variant = leg(t, path, 'initial_loss_20pct')
            variant['trigger_bid'] = q['bid']
            variant['floor'] = str(floor)
            break
    if variant is None:
        variant = (dict(control) if cap-previous <= timedelta(seconds=120)
                   else {'status': 'missing_path', 'reason': 'quote_gap_over_120s'})
    for value in (control,variant):
        if value['status'] == 'priced':
            pnl = (number(value['bid'])-ask)*100-D('3.30')
            value['net'] = str(pnl)
            value['return_pct'] = str(pnl/(ask*100+D('1.65'))*100)
    return {'date':entry['date'], 'contract':entry['contract'], 'entry_time':entry['entry_time'],
            'entry_ask':str(ask), 'entry_bid':str(number(entry['entry_bid'])),
            'control':control, 'variant':variant,
            'snapshots':[q for t,q in sorted(unique.items())]}


def stats(rows, arm, extra_cost='0'):
    ordered=sorted(rows,key=lambda r:at(r['entry_time']))
    values=[number(r[arm]['net'])-number(extra_cost) for r in ordered]
    gain=sum((x for x in values if x>0),D(0))
    loss=-sum((x for x in values if x<0),D(0))
    equity=peak=dd=D(0)
    for p in values:
        equity+=p; peak=max(peak,equity); dd=max(dd,peak-equity)
    returns=[(number(r[arm]['net'])-number(extra_cost))/(number(r['entry_ask'])*100+D('1.65'))*100 for r in ordered]
    return dict(count=len(values),wins=sum(x>0 for x in values), net=str(equity),
                pf=str(gain/loss) if loss else ('no_losses' if gain else None),
                drawdown=str(dd),median_return=str(median(returns)) if returns else None)


def compare(rows):
    paired=[r for r in rows if all(r[k]['status']=='priced' for k in ('control','variant'))]
    diffs=[number(r['variant']['net'])-number(r['control']['net']) for r in paired]
    group=lambda win: sum((number(r['variant']['net'])-number(r['control']['net']) for r in paired
                          if (number(r['control']['net'])>0 if win else number(r['control']['net'])<0)),D(0))
    return dict(paired=len(paired),unpaired=len(rows)-len(paired),control=stats(paired,'control'),
                variant=stats(paired,'variant'),extra_two_dollars_variant=stats(paired,'variant','2'),
                improved=sum(d>0 for d in diffs),worsened=sum(d<0 for d in diffs),unchanged=sum(d==0 for d in diffs),
                median_change=str(median(diffs)) if diffs else None,
                baseline_winner_change=str(group(True)),baseline_loser_change=str(group(False)),
                winners_to_losers=sum(number(r['control']['net'])>0>number(r['variant']['net']) for r in paired),
                losers_to_winners=sum(number(r['control']['net'])<0<number(r['variant']['net']) for r in paired),
                statuses={k:dict(Counter(r[k]['status'] for r in rows)) for k in ('control','variant')})


def stream_selected(z, member, entry):
    start=at(entry['entry_time']); end=start+timedelta(minutes=91)
    with z.open(member) as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as decoder:
        with io.TextIOWrapper(decoder,encoding='utf-8',newline='') as source:
            reader=csv.DictReader(source)
            required={'symbol','rtype','ts_recv','bid_px_00','ask_px_00','bid_sz_00','ask_sz_00'}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError('Missing snapshot provenance/price/size columns')
            for raw in reader:
                if raw['symbol'].strip()!=entry['contract']:
                    continue
                if raw['rtype']!='193': raise ValueError('Expected CBBO-1m')
                t=at(raw['ts_recv'])
                if t.second or t.microsecond: raise ValueError('Expected interval-end minute clock')
                if start <= t <= end:
                    yield dict(contract=entry['contract'],time=t.isoformat(),bid=raw['bid_px_00'],ask=raw['ask_px_00'],
                               bid_size=raw['bid_sz_00'],ask_size=raw['ask_sz_00'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','archive','plan','output'): p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    raw=args.baseline.read_bytes(); baseline=json.loads(raw)
    if (not baseline['complete'] or baseline['protocol']!='two_leg_causal_prefix_snapshot_clock_baseline_v2'
            or baseline['quote_clock_policy']!='cbbo_interval_end_ts_recv_v2'
            or len(baseline['rows'])!=baseline['sessions']):
        raise ValueError('Incomplete or wrong-clock baseline')
    dates=[r['date'] for r in baseline['rows']]
    if dates != sorted(set(dates)) or dates != sorted(r['date'] for r in baseline['manifest']):
        raise ValueError('Baseline date coverage mismatch')
    entries=[r for r in baseline['rows'] if r['status'] in ('priced','missing_exit')]
    if str(args.archive.resolve())!=baseline['archive']: raise ValueError('Wrong archive')
    identity={'protocol':PROTOCOL,'baseline_sha256':hashlib.sha256(raw).hexdigest(),
              'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'plan_sha256':hashlib.sha256(args.plan.read_bytes()).hexdigest()}
    if args.output.exists():
        result=json.loads(args.output.read_text())
        if any(result.get(k)!=v for k,v in identity.items()): raise ValueError('Checkpoint identity differs')
        if [r['date'] for r in result['rows']] != [r['date'] for r in entries[:len(result['rows'])]]:
            raise ValueError('Checkpoint entry cohort differs')
    else:
        result=dict(**identity,entries=len(entries),rows=[],complete=False,
                    coverage=dict(Counter(r['status'] for r in baseline['rows'])),
                    basis='Sampled minute-end quotes, not historical tick fills, exchange freshness or live results')
    with ZipFile(args.archive) as z:
        infos=sorted((i for i in z.infolist() if re.search(r'-\d{8}\.cbbo-1m\.(?:csv|dbn)(?:\.zst)?$',i.filename)),key=lambda i:i.filename)
        manifest=hashlib.sha256(json.dumps([(i.filename,i.CRC,i.file_size) for i in infos]).encode()).hexdigest()
        if manifest!=baseline['archive_manifest_sha256']: raise ValueError('Archive manifest differs')
        members={r['date']:r['member'] for r in baseline['manifest']}
        for entry in entries[len(result['rows']):]:
            if shutil.disk_usage(args.output.parent).free<2*1024**3: raise ValueError('Disk reserve low')
            result['rows'].append(replay(entry,list(stream_selected(z,members[entry['date']],entry))))
            result['complete']=len(result['rows'])==len(entries)
            result['summary']=compare(result['rows'])
            temp=args.output.with_suffix('.checkpoint.tmp')
            with temp.open('x') as target:
                json.dump(result,target,indent=2,allow_nan=False)
                target.flush();os.fsync(target.fileno())
            os.replace(temp,args.output)
            print(f"{len(result['rows'])}/{len(entries)} {entry['date']}: {result['rows'][-1]['variant']['status']}",flush=True)


if __name__=='__main__': main()
