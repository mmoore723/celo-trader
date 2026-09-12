"""Independently reconcile original-contract exit comparisons and exclusions."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path


def moment(value):
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError('Naive time')
    return t


def totals(rows, arm):
    vals = [D(r[arm]['net']) for r in rows]
    wins = sum((x for x in vals if x > 0), D(0))
    losses = -sum((x for x in vals if x < 0), D(0))
    return dict(count=len(vals), wins=sum(x > 0 for x in vals), net=str(sum(vals)),
                pf=str(wins/losses) if losses else ('no_losses' if wins else None))


def verify(result, retained):
    paths = {r['id']: r for r in retained['rows']}
    audited = {}
    for sid, policies in result['results'].items():
        expected = {key for key in paths if key.startswith(sid+'|')}
        audited[sid] = {}
        for policy, data in policies.items():
            ids = [sid+'|'+r['candidate_id'] for r in data['rows']]
            if len(ids) != len(set(ids)) or set(ids) != expected:
                raise ValueError('Missing or repeated entries')
            for row in data['rows']:
                source = paths[sid+'|'+row['candidate_id']]
                if row['independent'] != source['independent'] or row['contract'] != source['control']['contract']:
                    raise ValueError('Entry identity changed')
                book = {moment(q['time']): q for q in source['control_path']}
                start = moment(row['entry_time'])
                if start != moment(source['control']['entry_time']) or D(row['entry_ask']) != D(source['control']['entry_ask']):
                    raise ValueError('Original entry changed')
                if D(row['control']['net']) != D(source['control']['net']):
                    raise ValueError('Control P&L changed')
                if moment(row['control']['exit_time']) != moment(source['control']['exit_time']):
                    raise ValueError('Control exit time changed')
                for arm in ('control', 'variant'):
                    fill = row[arm]
                    if fill['status'] != 'priced':
                        if 'net' in fill:
                            raise ValueError('Unpriced result has fabricated P&L')
                        continue
                    time, decision = moment(fill['exit_time']), moment(fill['decision_at'])
                    if not start < decision < time <= decision+timedelta(minutes=1):
                        raise ValueError('Exit used current/future wrong snapshot')
                    if time > moment(source['control']['exit_time']) or time not in book:
                        raise ValueError('Exit outside retained source')
                    if D(fill['bid']) != D(book[time]['bid']):
                        raise ValueError('Wrong executable bid')
                    expected_net = (D(fill['bid'])-D(row['entry_ask']))*100-D('3.30')
                    if D(fill['net']) != expected_net:
                        raise ValueError('Exit arithmetic mismatch')
                last = start
                for step in row['trace']:
                    time = moment(step['time'])
                    if not last < time <= start+timedelta(minutes=30) or time not in book:
                        raise ValueError('Trace clock mismatch')
                    if D(step['option_bid']) != D(book[time]['bid']):
                        raise ValueError('Trace price mismatch')
                    last = time
            for name, rows in [('all_activity', data['rows']),
                               ('independent', [r for r in data['rows'] if r['independent']])]:
                paired = [r for r in rows if r['variant']['status'] == 'priced']
                stated = data[name]
                if stated['paired'] != len(paired) or stated['unpaired'] != len(rows)-len(paired):
                    raise ValueError('Incorrect comparison denominator')
                if stated['winners_to_losers'] != sum(D(r['control']['net']) > 0 > D(r['variant']['net']) for r in paired):
                    raise ValueError('Lost-winner count changed')
                for winner, field in [(True, 'baseline_winner_change'), (False, 'baseline_loser_change')]:
                    delta = sum((D(r['variant']['net'])-D(r['control']['net']) for r in paired
                                 if (D(r['control']['net']) > 0 if winner else D(r['control']['net']) < 0)), D(0))
                    if D(stated[field]) != delta:
                        raise ValueError('Winner/loser attribution mismatch')
                for arm in ('control', 'variant'):
                    calculated = totals(paired, arm)
                    if any(stated[arm][k] != calculated[k] for k in ('count', 'wins', 'pf')) or D(stated[arm]['net']) != D(calculated['net']):
                        raise ValueError('Summary does not reconcile')
            rows = [r for r in data['rows'] if r['independent']]
            missing = [r for r in rows if r['variant']['status'] != 'priced']
            audited[sid][policy] = dict(
                full_original_cohort=totals(rows, 'control'),
                excluded_original_outcomes=totals(missing, 'control'),
                excluded_reasons=dict(Counter(r['variant']['reason'] for r in missing)),
                excluded_ids=[r['candidate_id'] for r in missing],
                assessment='Not approved for deployment; paired results do not establish whole-cohort improvement')
    return audited


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'retained', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    result = json.loads(args.input.read_text())
    if not result['complete']:
        raise ValueError('Unfinished comparison')
    for group in ('input_sha256', 'code_sha256'):
        for name, digest in result[group].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                raise ValueError('Changed input or code: '+name)
    verified = verify(result, json.loads(args.retained.read_text()))
    output = dict(comparison_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  assessment='Share with caveats; no deployment approval', verified=verified)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
