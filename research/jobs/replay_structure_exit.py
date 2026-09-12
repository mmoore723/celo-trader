"""Paired structure-exit replay using retained same-contract option paths.

Currently accepts the complete, corrected-clock Two-Leg baseline and retained
119-contract archive extraction. Every baseline entry must be present; missing
stock/quote/warmup evidence excludes BOTH arms from paired totals, with counts.
Costs match the baseline: ask entry, later bid exit, $3.30 roundtrip per contract.
No inferred fills, network requests, order writes, or production imports.
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
from research.jobs.replay_two_leg_initial_loss import at, number, leg, replay, compare


def run_entry(entry, retained, market):
    verified = replay(entry, retained['snapshots'])
    d = 1 if entry['direction'] == 'bullish' else -1
    if entry['direction'] not in ('bullish','bearish'):
        raise ValueError('Unknown direction')
    state = ExitState(d, entry['stock_reference'], entry['entry_context']['v2_stop'],
                      entry['entry_ask'], at(entry['entry_time']), 90)
    path = [q for q in verified['snapshots'] if at(q['time']) > state.entry_time]
    cap = state.entry_time+timedelta(minutes=90)
    previous = state.entry_time
    trace = []
    variant = None
    for q in path:
        now = at(q['time'])
        if now > cap:
            break
        if now-previous > timedelta(seconds=120):
            variant = dict(status='missing_path',reason='quote_gap_over_120s')
            break
        previous = now
        try:
            context = market.at(now)
        except ValueError as exc:
            variant = dict(status='missing_context',reason=str(exc),time=now.isoformat())
            break
        decision = state.step(context,float(q['bid']))
        trace.append(dict(time=now.isoformat(), **decision, stock_close=context['close'],
                          option_bid=q['bid'],relative_volume=context['relative_volume'],
                          supports=context['supports'],resistances=context['resistances'],
                          frames=context['frames']))
        if decision['action'] == 'missing_context':
            variant = dict(status='missing_context',reason=decision['reason'],time=now.isoformat())
            break
        if decision['action'] == 'exit':
            variant = leg(now,path,decision['reason'])
            break
    if variant is None:
        variant = (leg(cap,path,'original_time_cap') if cap-previous <= timedelta(seconds=120)
                   else dict(status='missing_path',reason='quote_gap_over_120s'))
    if variant['status'] == 'priced':
        variant['net'] = str((number(variant['bid'])-number(entry['entry_ask']))*100-number('3.30'))
    return dict(date=entry['date'],contract=entry['contract'],entry_time=entry['entry_time'],
                entry_ask=str(entry['entry_ask']),control=verified['control'],variant=variant,trace=trace)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','retained','bars','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; never overwrite evidence')
    baseline_raw, retained_raw = args.baseline.read_bytes(), args.retained.read_bytes()
    baseline, retained = json.loads(baseline_raw),json.loads(retained_raw)
    if (baseline.get('protocol') != 'two_leg_causal_prefix_snapshot_clock_baseline_v2'
            or baseline.get('quote_clock_policy') != 'cbbo_interval_end_ts_recv_v2'
            or not baseline.get('complete') or not retained.get('complete')
            or len(baseline['rows']) != baseline['sessions']
            or retained['baseline_sha256'] != hashlib.sha256(baseline_raw).hexdigest()):
        raise ValueError('Baseline or retained-path identity mismatch')
    data = load_csv(args.bars)
    if data.sha256 != baseline['bars_sha256']:
        raise ValueError('Stock bars changed')
    entries = [r for r in baseline['rows'] if r['status'] in ('priced','missing_exit')]
    paths = {r['date']:r for r in retained['rows']}
    if len(paths) != len(retained['rows']) or set(paths) != {r['date'] for r in entries}:
        raise ValueError('Retained contract cohort incomplete')
    market = MarketContext(data.bars)
    rows = []
    for entry in entries:
        prior = paths[entry['date']]
        if prior['contract'] != entry['contract'] or at(prior['entry_time']) != at(entry['entry_time']):
            raise ValueError('Entry identity changed')
        row = run_entry(entry,prior,market)
        rows.append(row)
        print(f'{len(rows)}/{len(entries)} {entry["date"]}: {row["variant"]["status"]} {row["variant"]["reason"]}',flush=True)
    code_paths = [Path(__file__),Path(__file__).with_name('structure_exit_candidate.py'),
                  Path(__file__).with_name('replay_two_leg_initial_loss.py')]
    result = dict(protocol=PROTOCOL,complete=True,baseline_sha256=hashlib.sha256(baseline_raw).hexdigest(),
                  retained_sha256=hashlib.sha256(retained_raw).hexdigest(),bars_sha256=data.sha256,
                  code_sha256={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in code_paths},
                  summary=compare(rows),exit_reasons=dict(Counter(r['variant']['reason'] for r in rows)),
                  limitation='Historical paired diagnostic only; not holdout validation or whole-account proof.',rows=rows)
    fd = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        json.dump(result,handle,indent=2)
    print(json.dumps(dict(summary=result['summary'],exit_reasons=result['exit_reasons'])),flush=True)


if __name__ == '__main__':
    main()
