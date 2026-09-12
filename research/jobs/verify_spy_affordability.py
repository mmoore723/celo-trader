"""Independent retained-path checks and a fixed-cohort account diagnostic.

Does not download data, invoke broker APIs, change settings, or select new
parameters. Source contracts were selected under the INITIAL $1.42 cap.
Production quantity/capacity rules are applied to evolving account equity,
but contract selection is not rerun with that evolving budget.
"""
import argparse
from collections import Counter
import contextlib
import csv
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import io
import json
import os
from pathlib import Path
import re

from research.jobs.replay_account_controls import replay

FILES = {
    'V2_SPY_TREND_CONT': 'spy_trend_corrected_clock_baseline_2026-09-11.json',
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': 'failed_range_corrected_clock_baseline_2026-09-11.json',
    'V2_SPY_AFTERNOON_FVG': 'fvg_corrected_clock_baseline_2026-09-11.json',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clock(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Naive quote clock')
    return dt


def metrics(values):
    values = [D(str(x)) for x in values]
    wins = sum((x for x in values if x > 0), D(0))
    losses = -sum((x for x in values if x < 0), D(0))
    return dict(count=len(values), wins=sum(x > 0 for x in values),
                net=float(sum(values)), gross_wins=float(wins), gross_losses=float(losses),
                pf=float(wins / losses) if losses else None)


def check_leg(leg, path, original, candidate=False):
    if leg['status'] != 'priced':
        if candidate and leg['status'] in {'no_affordable_contract', 'missing_exit'}:
            return
        raise ValueError('Unexpected price status')
    start, end = clock(leg['entry_time']), clock(leg['exit_time'])
    if start != clock(original['entry_time']) or end != clock(original['exit_time']):
        raise ValueError('Changed entry or exit time')
    if end - start != timedelta(minutes=31):
        raise ValueError('Wrong next-snapshot exit')
    times = [clock(q['time']) for q in path]
    if not times or times != sorted(set(times)) or times[0] != start or times[-1] != end:
        raise ValueError('Missing, duplicated or reordered endpoint')
    for q, time in zip(path, times):
        nums = [D(q[k]) for k in ('bid', 'ask', 'bid_size', 'ask_size')]
        if not all(n.is_finite() and n > 0 for n in nums) or nums[0] > nums[1]:
            raise ValueError('Unusable quote')
        if q['contract'] != leg['contract'] or not start <= time <= end or time.second or time.microsecond:
            raise ValueError('Wrong contract or minute')
    if any(D(path[0][name]) != D(leg['entry_' + name]) for name in ('ask', 'bid')):
        raise ValueError('Entry not supported by retained quote')
    if D(path[-1]['bid']) != D(leg['exit_bid']):
        raise ValueError('Exit not supported by retained quote')
    expected = (D(leg['exit_bid']) - D(leg['entry_ask'])) * 100 - D('3.30')
    if expected != D(leg['net']):
        raise ValueError('Incorrect modeled P&L')
    if not candidate:
        if leg['contract'] != original['contract'] or any(
                D(leg[k]) != D(str(original[k])) for k in ('entry_ask', 'entry_bid', 'exit_bid')):
            raise ValueError('Control changed from original source')
        if abs(expected - D(str(original['net_pnl_one_contract']))) > D('.000002'):
            raise ValueError('Original control cost mismatch')
    else:
        symbol = re.fullmatch(r'SPY\s*(\d{6})([CP])(\d{8})', leg['contract'])
        if symbol is None:
            raise ValueError('Unrecognized OCC contract')
        expiry = datetime.strptime(symbol[1], '%y%m%d').date()
        strike = D(symbol[3]) / 1000
        bullish = original['direction'] == 'bullish'
        spot = D(str(original['stock_reference']))
        ask, bid = D(leg['entry_ask']), D(leg['entry_bid'])
        if not 7 <= (expiry - start.date()).days <= 21 or symbol[2] != ('C' if bullish else 'P'):
            raise ValueError('Wrong expiry or direction')
        if not (strike > spot if bullish else strike < spot):
            raise ValueError('Not out of the money')
        if not D('.8') <= ask <= D('1.42') or (ask-bid)/((ask+bid)/2) > D('.08'):
            raise ValueError('Budget or spread filter failed')


def validate(data, originals):
    if not data['complete'] or data['protocol'] != 'spy_three_strategies_affordability_fixed142_v1':
        raise ValueError('Incomplete or unexpected protocol')
    ids = [r['id'] for r in data['rows']]
    if len(ids) != len(set(ids)) or set(ids) != set(originals):
        raise ValueError('Entry cohort changed')
    for row in data['rows']:
        original = originals[row['id']]
        if row['strategy_id'] != row['id'].split('|')[0]:
            raise ValueError('Strategy identity changed')
        if row['independent'] != original['independent'] or row['date'] != original['date']:
            raise ValueError('Cohort membership changed')
        if row['control_fits_initial_budget'] != (D(row['control']['entry_ask']) <= D('1.42')):
            raise ValueError('Incorrect affordability flag')
        for name in ('control', 'candidate'):
            check_leg(row[name], row[name + '_path'], original, candidate=name == 'candidate')


def summarize(rows):
    result = {}
    for sid in FILES:
        result[sid] = {}
        for cohort in ('all', 'non_overlapping'):
            selected = [r for r in rows if r['strategy_id'] == sid and (cohort == 'all' or r['independent'])]
            paired = [r for r in selected if r['candidate']['status'] == 'priced']
            result[sid][cohort] = dict(
                entries=len(selected), candidate_status=dict(Counter(r['candidate']['status'] for r in selected)),
                control=metrics(r['control']['net'] for r in selected),
                candidate=metrics(r['candidate']['net'] for r in paired),
                control_on_candidate_priced_cohort=metrics(r['control']['net'] for r in paired),
                winner_to_loser=sum(D(r['control']['net']) > 0 > D(r['candidate']['net']) for r in paired),
                winner_change=float(sum((D(r['candidate']['net'])-D(r['control']['net'])
                                         for r in paired if D(r['control']['net']) > 0), D(0))),
                loser_change=float(sum((D(r['candidate']['net'])-D(r['control']['net'])
                                        for r in paired if D(r['control']['net']) < 0), D(0))))
    return result


def portfolio(rows, settings, sessions):
    results = {}
    for leg in ('control', 'candidate'):
        trades, quotes, source = [], [], {}
        for row in rows:
            if not row['independent'] or row[leg]['status'] != 'priced':
                continue
            fill, path, tid = row[leg], row[leg + '_path'], row['id']
            source[tid] = path
            trades.append(dict(id=tid, strategy_id=row['strategy_id'], contract_symbol=fill['contract'],
                               entry_time=fill['entry_time'], exit_time=fill['exit_time'],
                               entry_price=fill['entry_ask'], entry_bid=fill['entry_bid'],
                               exit_price=fill['exit_bid'], entry_size=path[0]['ask_size'], contracts=1))
            quotes.extend(dict(trade_id=tid, observed_at=q['time'], bid=q['bid']) for q in path)
        for friction in (0, .01, .05):
            # $1.65 each side reproduces the fixed $3.30 baseline total cost.
            with contextlib.redirect_stdout(io.StringIO()) as warnings:
                r = replay(trades, quotes, settings, fee_per_side=1.65,
                           friction_per_side=friction, settlement_sessions=sessions)
            r['sizing_warning_lines'] = len(warnings.getvalue().splitlines())
            r['insufficient_exit_depth'] = [c['id'] for c in r['closed']
                                           if D(source[c['id']][-1]['bid_size']) < c['quantity']]
            r['hypothetical_fill_checks_pass'] = (not r['insufficient_exit_depth'] and
                r['performance_valid_without_emergency_repricing'] and not r['stale_mark_uses_at_entry'])
            r['skip_counts'] = dict(Counter(d['reason'] for d in r['decisions'] if d['action'] == 'skip'))
            r['by_strategy'] = {sid: metrics(c['pnl'] for c in r['closed'] if c['id'].startswith(sid+'|'))
                                for sid in FILES}
            if abs(sum(c['pnl'] for c in r['closed']) - r['net_pnl']) > 1e-6 or r['open_at_end']:
                raise ValueError('Account ledger does not reconcile')
            if abs(sum(r['daily_pnl'].values()) - r['net_pnl']) > 1e-6 or r['max_open'] > settings['max_concurrent_positions']:
                raise ValueError('Daily ledger or position limit mismatch')
            results[f'{leg}_friction_{friction}'] = r
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'baselines', 'settings', 'bars', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    data = json.loads(args.input.read_text())
    if data['code_sha256'] != sha(Path(__file__).with_name('replay_spy_affordable_contracts.py')):
        raise ValueError('Replay code hash changed')
    originals = {}
    for sid, filename in FILES.items():
        path = args.baselines / filename
        if sha(path) != data['baseline_sha256'][sid]:
            raise ValueError('Baseline hash changed')
        baseline = json.loads(path.read_text())
        for row in baseline['rows']:
            if row.get('profile', 'reviewed_bounds') != 'reviewed_bounds':
                continue
            if sid == 'V2_FAILED_OR_BREAK_VWAP_REVERSION' and not row['native']:
                continue
            originals[sid + '|' + row['candidate_id']] = row
    validate(data, originals)
    verified = json.loads(args.settings.read_text())
    if not verified['all_checks_pass']:
        raise ValueError('Settings snapshot not verified')
    with args.bars.open() as src:
        sessions = sorted({clock(row['timestamp']).date().isoformat() for row in csv.DictReader(src)})
    output = dict(protocol='spy_affordability_independent_verification_account_v1',
                  input_sha256={str(path): sha(path) for path in (args.input, args.settings, args.bars, Path(__file__),
                    Path(__file__).with_name('replay_account_controls.py'))},
                  verified_entries=len(originals), summary=summarize(data['rows']),
                  account=portfolio(data['rows'], verified['risk_settings'], sessions),
                  limitations=[
                    'Fixed initial ask cap; contract selection is not rerun with evolving equity',
                    'Only three enabled SPY strategies, not all six or all historical signals',
                    'Account cohort retains original within-strategy non-overlap filter',
                    'Ties between strategies use stable strategy ID order, not a verified scheduler order',
                    'Next observed stock session is a conservative settlement model, not broker cash verification',
                    'Current settings, not historical configuration revisions',
                    'Instantaneous displayed-size fills; no order latency or queue simulation',
                    'CBBO minute snapshots provide sampled drawdown, not intraminute worst loss',
                    'Independent verification checks chosen contracts; full-chain ranking is covered by replay tests',
                    'Development diagnostic, not an untouched holdout or future profitability claim'])
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(output, out, indent=2, allow_nan=False)
    print(json.dumps({'verified_entries': len(originals), 'summary': output['summary'],
                      'account': {name: {k: r[k] for k in ('ending_equity', 'net_pnl', 'pf', 'max_open',
                          'sampled_drawdown', 'longest_losing_streak', 'skip_counts', 'hypothetical_fill_checks_pass',
                          'by_strategy')} for name, r in output['account'].items()}}, indent=2))


if __name__ == '__main__':
    main()
