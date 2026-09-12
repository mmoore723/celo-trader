"""Independent audit of fallback timing, original decisions and full cohorts."""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path


def time(value):
    return datetime.fromisoformat(value)


def key(row):
    return row['contract'], time(row['entry_time']), row.get('candidate_id', '')


def check_pair(row, original, quotes):
    for name in ('control', 'trace', 'contract', 'entry_time', 'entry_ask'):
        if row[name] != original[name]:
            raise ValueError('Original evidence changed: '+name)
    if row['prior_variant'] != original['variant'] or row.get('independent') != original.get('independent'):
        raise ValueError('Prior comparison or independence changed')
    expected_fallback = original['variant']['status'] == 'missing_context'
    if row['context_fallback_used'] != expected_fallback:
        raise ValueError('Fallback classification differs')
    if not expected_fallback:
        if row['variant'] != original['variant']:
            raise ValueError('Previously evaluated exit changed')
        return
    failed, cap = time(original['variant']['time']), time(original['control']['decision_at'])
    ordered = sorted(quotes, key=lambda q: time(q['time']))
    previous = max(time(q['time']) for q in ordered if time(q['time']) < failed)
    decision, reason = cap, 'original_time_cap'
    for q in ordered:
        now = time(q['time'])
        if not failed <= now <= cap:
            continue
        if now-previous > timedelta(seconds=120):
            if row['variant']['status'] != 'missing_path':
                raise ValueError('Quote gap was hidden')
            return
        previous = now
        if D(q['bid']) <= D(row['entry_ask'])*D('.80'):
            decision, reason = now, 'maximum_premium_loss_20pct'
            break
    exit_quote = next((q for q in ordered if decision < time(q['time']) <= decision+timedelta(seconds=60)), None)
    result = row['variant']
    if exit_quote is None:
        if result['status'] != 'missing_quote':
            raise ValueError('Missing next quote filled anyway')
        return
    if result['status'] != 'priced' or time(result['decision_at']) != decision or result['reason'] != reason:
        raise ValueError('Wrong guard/timer decision')
    if time(result['exit_time']) != time(exit_quote['time']) or D(result['bid']) != D(exit_quote['bid']):
        raise ValueError('Wrong later executable quote')
    expected_net = (D(exit_quote['bid'])-D(row['entry_ask']))*100-D('3.30')
    if D(result['net']) != expected_net:
        raise ValueError('Fallback cost arithmetic mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('audit-dir', 'input', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    load = lambda name: json.loads((args.audit_dir/name).read_text())
    result = json.loads(args.input.read_text())
    if not result['complete']:
        raise ValueError('Incomplete result')
    for group in ('input_sha256', 'code_sha256'):
        for filename, expected in result[group].items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
                raise ValueError('Changed source or algorithm')
    originals = {}
    for sid, names in {
        'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('two_leg_structure_retest_v1.json', 'two_leg_structure_alignment_v2.json'),
        'V2_SPY_TREND_CONT': ('spy_structure_retest_v1.json', 'spy_structure_alignment_v2.json'),
    }.items():
        originals[sid] = {load(name)['protocol']: load(name)['rows'] for name in names}
    for sid, policies in load('other_spy_structure_comparison_v1.json')['results'].items():
        originals[sid] = {name: data['rows'] for name, data in policies.items()}
    twopaths = {key(r): r['snapshots'] for r in load('two_leg_initial_loss20_comparison.json')['rows']}
    spypaths = {r['id']: r['control_path'] for r in load('spy_three_strategy_affordability_v1.json')['rows']}
    verified = []
    for sid, policies in result['results'].items():
        for policy, data in policies.items():
            prior = {key(r): r for r in originals[sid][policy]}
            current = {key(r): r for r in data['rows']}
            if len(current) != len(data['rows']) or set(current) != set(prior):
                raise ValueError('Original cohort changed')
            for k, row in current.items():
                path = twopaths[k] if sid.startswith('V2_TSLA') else spypaths[sid+'|'+row['candidate_id']]
                check_pair(row, prior[k], path)
            for cohort, rows in [('all_activity', data['rows']),
                                 ('independent', [r for r in data['rows'] if r.get('independent', True)])]:
                paired = [r for r in rows if r['variant']['status'] == 'priced']
                summary = data[cohort]
                if summary['paired'] != len(paired) or summary['unpaired'] != len(rows)-len(paired):
                    raise ValueError('Incorrect denominator')
                for arm in ('control', 'variant'):
                    vals = [D(r[arm]['net']) for r in paired]
                    gain, loss = sum((v for v in vals if v > 0), D(0)), -sum((v for v in vals if v < 0), D(0))
                    if D(summary[arm]['net']) != sum(vals) or (loss and D(summary[arm]['pf']) != gain/loss):
                        raise ValueError('Incorrect full-cohort P&L or PF')
                if summary['winners_to_losers'] != sum(D(r['control']['net']) > 0 > D(r['variant']['net']) for r in paired):
                    raise ValueError('Lost winners hidden')
            verified.append(dict(strategy=sid, policy=policy, entries=len(current),
                                 fallback_entries=data['fallback_count'], unpaired=data['all_activity']['unpaired']))
    output = dict(assessment='Share with caveats; none approved for deployment', verified=verified,
                  input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
