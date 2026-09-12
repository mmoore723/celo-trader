"""One predeclared alignment ablation on the existing Two-Leg cohort."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from research.engine.data import load_csv
from research.jobs.structure_exit_candidate import MarketContext
from research.jobs.structure_alignment_candidate import AlignmentExitState, PROTOCOL
from research.jobs.replay_structure_exit import run_entry
from research.jobs.replay_two_leg_initial_loss import at, compare


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','retained','bars','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise ValueError('Output exists')
    raw=args.baseline.read_bytes();baseline=json.loads(raw)
    retained_raw=args.retained.read_bytes();retained=json.loads(retained_raw)
    if (baseline['protocol']!='two_leg_causal_prefix_snapshot_clock_baseline_v2'
            or baseline['quote_clock_policy']!='cbbo_interval_end_ts_recv_v2'
            or not baseline['complete'] or not retained['complete']
            or len(baseline['rows'])!=baseline['sessions']
            or hashlib.sha256(raw).hexdigest()!=retained['baseline_sha256']):
        raise ValueError('Invalid baseline or retained data')
    data=load_csv(args.bars)
    if data.sha256!=baseline['bars_sha256']:
        raise ValueError('Changed bars')
    entries=[r for r in baseline['rows'] if r['status'] in ('priced','missing_exit')]
    paths={r['date']:r for r in retained['rows']}
    if len(paths)!=len(retained['rows']) or set(paths)!={r['date'] for r in entries}:
        raise ValueError('Incomplete cohort')
    market=MarketContext(data.bars)
    rows=[]
    for entry in entries:
        prior=paths[entry['date']]
        if prior['contract']!=entry['contract'] or at(prior['entry_time'])!=at(entry['entry_time']):
            raise ValueError('Changed entry')
        rows.append(run_entry(entry,prior,market,state_type=AlignmentExitState))
    sources=['structure_alignment_candidate.py','structure_exit_candidate.py',
             'replay_structure_exit.py','replay_two_leg_initial_loss.py',Path(__file__).name]
    result=dict(protocol=PROTOCOL,complete=True,baseline_sha256=hashlib.sha256(raw).hexdigest(),
        retained_sha256=hashlib.sha256(retained_raw).hexdigest(),bars_sha256=data.sha256,
        code_sha256={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources},
        summary=compare(rows),exit_reasons=dict(Counter(r['variant']['reason'] for r in rows)),rows=rows,
        limitation='Development-selected follow-up. Not holdout validation or whole-account proof.')
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as output:
        json.dump(result,output,indent=2)
    print(json.dumps({k:result[k] for k in ('summary','exit_reasons')}),flush=True)


if __name__=='__main__':
    main()
