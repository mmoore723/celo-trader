"""Apply the frozen structure_retest_v1 to SPY's unchanged 30-minute cohort.

Uses the same initial thesis stop and contract as the baseline. Fees/friction
match its $3.30 per-contract roundtrip cost. Report all activity and the original
non-overlapping subset separately. No entry changes or parameter retuning.
"""
import argparse
from collections import Counter
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path

from research.engine.data import load_csv
from research.jobs.structure_exit_candidate import ExitState, MarketContext, PROTOCOL
from research.jobs.replay_two_leg_initial_loss import at, number, leg, usable, compare


def evaluate_pair(entry, retained, market):
    if entry['direction'] not in ('bullish','bearish'):
        raise ValueError('Unknown direction')
    start = at(entry['entry_time'])
    cap = start+timedelta(minutes=30)
    quotes = {}
    for q in retained['snapshots']:
        t = at(q['time'])
        if q['contract'] != entry['contract'] or not start <= t <= cap+timedelta(seconds=60):
            raise ValueError('Unexpected quote identity or clock')
        if not usable(q):
            continue
        if t in quotes and quotes[t] != q:
            raise ValueError('Conflicting quote snapshot')
        quotes[t] = q
    if start not in quotes or any(number(quotes[start][k])!=number(entry['entry_'+k]) for k in ('ask','bid')):
        raise ValueError('Entry quote not reproduced')
    path = [q for t,q in sorted(quotes.items()) if t>start]
    control = leg(cap,path,'fixed_30m')
    if (control['status']!='priced' or number(control['bid'])!=number(entry['exit_bid'])
            or at(control['exit_time'])!=at(entry['exit_time'])):
        raise ValueError('Original control not reproduced')
    control['net'] = str((number(control['bid'])-number(entry['entry_ask']))*100-number('3.30'))
    if abs(number(control['net'])-number(entry['net_pnl_one_contract']))>number('.000002'):
        raise ValueError('Original control costs differ')
    state = ExitState(1 if entry['direction']=='bullish' else -1,entry['stock_reference'],
                      entry['signal_meta']['v2_stop'],entry['entry_ask'],start,30)
    previous, variant, trace = start,None,[]
    for q in path:
        now = at(q['time'])
        if now>cap:
            break
        if now-previous>timedelta(seconds=120):
            variant = dict(status='missing_path',reason='quote_gap_over_120s')
            break
        previous = now
        try:
            context = market.at(now)
        except ValueError as exc:
            variant = dict(status='missing_context',reason=str(exc),time=now.isoformat())
            break
        decision = state.step(context,float(q['bid']))
        trace.append(dict(time=now.isoformat(),**decision,stock_close=context['close'],option_bid=q['bid'],
                          relative_volume=context['relative_volume'],supports=context['supports'],
                          resistances=context['resistances'],frames=context['frames']))
        if decision['action']=='missing_context':
            variant = dict(status='missing_context',reason=decision['reason'],time=now.isoformat())
            break
        if decision['action']=='exit':
            variant = leg(now,path,decision['reason'])
            break
    if variant is None:
        variant = (leg(cap,path,'original_time_cap') if cap-previous<=timedelta(seconds=120)
                   else dict(status='missing_path',reason='quote_gap_over_120s'))
    if variant['status']=='priced':
        variant['net'] = str((number(variant['bid'])-number(entry['entry_ask']))*100-number('3.30'))
    return dict(date=entry['date'],candidate_id=entry['candidate_id'],independent=entry['independent'],
                contract=entry['contract'],entry_time=entry['entry_time'],entry_ask=str(entry['entry_ask']),
                control=control,variant=variant,trace=trace)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','retained','manifest','bars','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists')
    raw=args.baseline.read_bytes();baseline=json.loads(raw)
    retained_raw=args.retained.read_bytes();retained=json.loads(retained_raw)
    manifest_raw=args.manifest.read_bytes();manifest=json.loads(manifest_raw)
    if (baseline['protocol']!='spy_trend_cbbo_interval_end_30m_research_v1'
            or baseline['quote_clock_policy']!='cbbo_interval_end_ts_recv_v2'
            or not baseline['complete'] or not retained['complete']
            or baseline['manifest_sha256']!=hashlib.sha256(manifest_raw).hexdigest()
            or retained['baseline_sha256']!=hashlib.sha256(raw).hexdigest()):
        raise ValueError('Incomplete or mismatched sources')
    entries=baseline['rows'];paths={r['candidate_id']:r for r in retained['rows']}
    if (len(paths)!=len(retained['rows']) or len(entries)!=baseline['candidates']
            or set(paths)!={r['candidate_id'] for r in entries}):
        raise ValueError('Incomplete candidate coverage')
    data=load_csv(args.bars)
    if data.sha256!=manifest['bars_sha256']:
        raise ValueError('Stock bars differ from entry manifest')
    market=MarketContext(data.bars)
    rows=[]
    for entry in entries:
        row=evaluate_pair(entry,paths[entry['candidate_id']],market)
        rows.append(row)
        print(f'{len(rows)}/{len(entries)} {row["candidate_id"]}: {row["variant"]["status"]}',flush=True)
    files=[Path(__file__),Path(__file__).with_name('structure_exit_candidate.py'),
           Path(__file__).with_name('replay_two_leg_initial_loss.py')]
    result=dict(protocol=PROTOCOL,complete=True,baseline_sha256=hashlib.sha256(raw).hexdigest(),
                retained_sha256=hashlib.sha256(retained_raw).hexdigest(),bars_sha256=data.sha256,
                code_sha256={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in files},
                all_activity=compare(rows),independent=compare([r for r in rows if r['independent']]),
                exit_reasons=dict(Counter(r['variant']['reason'] for r in rows)),rows=rows,
                limitation='Historical diagnostic only; not holdout validation or whole-account proof.')
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as output:
        json.dump(result,output,indent=2)
    print(json.dumps({k:result[k] for k in ('all_activity','independent','exit_reasons')}),flush=True)


if __name__=='__main__':
    main()
