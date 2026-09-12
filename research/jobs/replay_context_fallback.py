"""Explicit missing-context behavior for the frozen structure-exit candidates.

Before context fails, preserve every original decision. At the FIRST missing
candle/indicator context, stop making structural decisions for that position.
Keep the original time cap and independent 20% premium safeguard active using
only observed same-contract bids. Never restart structure analysis mid-trade.
Fill at the next available snapshot within 60s, not the triggering quote.
Quote gaps over 120s remain unknown and unpriced, never fabricated holds.

This is a separately named research policy, not an imputation of earlier missing
results and not production wiring. Prior comparisons remain immutable.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess

from research.jobs.replay_two_leg_initial_loss import at, number, usable, leg, compare

PROTOCOL = 'structure_context_fallback_20pct_v1'
# The first experiments predate the optional state_type/candidate selector.
# Their recorded source hashes match this exact committed producer, not today's
# extended runner. This wrapper reuses immutable results, not historical code.
ORIGINAL_PRODUCER_COMMIT = 'aca84ba949512a5d92a3cde3f9c448b6e6a81c28'


def complete_pair(original, snapshots):
    row = deepcopy(original)
    start = at(row['entry_time'])
    cap = at(row['control']['decision_at'])
    if cap-start not in (timedelta(minutes=30), timedelta(minutes=90)):
        raise ValueError('Unexpected original time cap')
    book = {}
    for q in snapshots:
        now = at(q['time'])
        if q['contract'] != row['contract'] or not start <= now <= cap+timedelta(minutes=1):
            raise ValueError('Wrong quote identity or clock')
        if not usable(q):
            raise ValueError('Unusable retained quote')
        if now in book and book[now] != q:
            raise ValueError('Conflicting quote')
        book[now] = q
    if start not in book or number(book[start]['ask']) != number(row['entry_ask']):
        raise ValueError('Original entry not reproduced')
    end = at(row['control']['exit_time'])
    if end not in book or number(book[end]['bid']) != number(row['control']['bid']):
        raise ValueError('Original control not reproduced')
    expected = (number(book[end]['bid'])-number(row['entry_ask']))*100-number('3.30')
    if expected != number(row['control']['net']):
        raise ValueError('Original cost arithmetic differs')
    row['prior_variant'] = deepcopy(row['variant'])
    row['context_fallback_used'] = row['variant']['status'] == 'missing_context'
    row['fallback_trace'] = []
    if not row['context_fallback_used']:
        return row
    failed_at = at(row['variant']['time'])
    if failed_at not in book or not start < failed_at <= cap:
        raise ValueError('Missing-context clock not observed')
    row['fallback_at'] = failed_at.isoformat()
    row['fallback_reason'] = row['variant']['reason']
    path = [q for time,q in sorted(book.items()) if time > start]
    previous = max(time for time in book if time < failed_at)
    variant = None
    floor = number(row['entry_ask'])*number('.80')
    for q in path:
        now = at(q['time'])
        if now < failed_at:
            continue
        if now > cap:
            break
        if now-previous > timedelta(seconds=120):
            variant = dict(status='missing_path', reason='fallback_quote_gap_over_120s')
            break
        previous = now
        reason = ('maximum_premium_loss_20pct' if number(q['bid']) <= floor else
                  'original_time_cap' if now >= cap else None)
        row['fallback_trace'].append(dict(time=now.isoformat(), option_bid=q['bid'],
            action='exit' if reason else 'hold_original_cap_with_guard', reason=reason))
        if reason:
            variant = leg(now, path, reason)
            break
    if variant is None:
        variant = (leg(cap, path, 'original_time_cap') if cap-previous <= timedelta(seconds=120)
                   else dict(status='missing_path', reason='fallback_quote_gap_over_120s'))
    if variant['status'] == 'priced':
        variant['net'] = str((number(variant['bid'])-number(row['entry_ask']))*100-number('3.30'))
    row['variant'] = variant
    return row


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists')
    hashes = {}
    historical_code = {}

    def load(name):
        file = args.audit_dir/name
        hashes[str(file)] = fingerprint(file)
        data = json.loads(file.read_text())
        if not data['complete']:
            raise ValueError('Incomplete source')
        # Preserve the exact source algorithms as well as their result files.
        for filename, digest in data.get('code_sha256', {}).items() if isinstance(data.get('code_sha256'), dict) else []:
            path = Path(filename) if Path(filename).is_absolute() else Path(__file__).with_name(filename)
            if fingerprint(path) != digest:
                if path.name not in ('replay_structure_exit.py', 'replay_spy_structure_exit.py'):
                    raise ValueError('Source code changed: '+filename)
                blob = subprocess.check_output(['git', 'show', ORIGINAL_PRODUCER_COMMIT+':research/jobs/'+path.name],
                                               cwd=Path(__file__).resolve().parents[2])
                if hashlib.sha256(blob).hexdigest() != digest:
                    raise ValueError('Historical producer hash not reproduced: '+filename)
                historical_code[name+'|'+path.name] = dict(commit=ORIGINAL_PRODUCER_COMMIT, sha256=digest)
        return data

    two = load('two_leg_initial_loss20_comparison.json')
    spy = load('spy_three_strategy_affordability_v1.json')
    twopaths = {(r['contract'], at(r['entry_time'])): r['snapshots'] for r in two['rows']}
    spypaths = {r['id']: r['control_path'] for r in spy['rows']}
    inputs = []
    for name in ('two_leg_structure_retest_v1.json', 'two_leg_structure_alignment_v2.json'):
        data = load(name)
        if data['retained_sha256'] != hashes[str(args.audit_dir/'two_leg_initial_loss20_comparison.json')]:
            raise ValueError('Two-Leg retained paths changed')
        inputs.append(('V2_TSLA_TWO_LEG_TREND_PULLBACK', data['protocol'], data['rows'],
                       lambda row: twopaths[(row['contract'], at(row['entry_time']))]))
    for name in ('spy_structure_retest_v1.json', 'spy_structure_alignment_v2.json'):
        data = load(name)
        sid = 'V2_SPY_TREND_CONT'
        inputs.append((sid, data['protocol'], data['rows'],
                       lambda row: spypaths['V2_SPY_TREND_CONT|'+row['candidate_id']]))
    others = load('other_spy_structure_comparison_v1.json')
    for sid, policies in others['results'].items():
        for policy, data in policies.items():
            inputs.append((sid, policy, data['rows'], lambda row, sid=sid: spypaths[sid+'|'+row['candidate_id']]))
    results = {}
    for sid, policy, rows, paths in inputs:
        complete = [complete_pair(row, paths(row)) for row in rows]
        result = dict(rows=complete, all_activity=compare(complete),
            independent=compare([r for r in complete if r.get('independent', True)]),
            fallback_count=sum(r['context_fallback_used'] for r in complete),
            exit_reasons=dict(Counter(r['variant']['reason'] for r in complete)))
        results.setdefault(sid, {})[policy] = result
        print(sid, policy, json.dumps({k:v for k,v in result.items() if k != 'rows'}), flush=True)
    code = [Path(__file__), Path(__file__).with_name('replay_two_leg_initial_loss.py')]
    output = dict(protocol=PROTOCOL, complete=True, input_sha256=hashes,
        historical_producer_code=historical_code,
        code_sha256={str(x):fingerprint(x) for x in code}, results=results,
        limitations=['Previously missing cases use a NEW declared fallback policy, not inferred original behavior',
                     'Original entries/contracts and costs unchanged; no new parameter search',
                     'Four enabled strategies, not all six; different SPY and TSLA date ranges',
                     'Snapshot-priced research only; 20% trigger is not a guaranteed maximum fill loss',
                     'Not full-account or untouched holdout validation; no deployment approval'])
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(output, out, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
