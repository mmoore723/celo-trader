"""Combine frozen, verified experiments, not a full six-strategy acceptance.

Uses the overlap of supplied stock-data calendars, never a date range selected
by profit. Does not optimize parameters or infer no-setup days from absent
trades. Native ORB and complete scheduler opportunity coverage remain missing.
No broker calls, settings mutations, archive extraction, or runtime wiring.
"""
import argparse
from collections import Counter
import contextlib
import csv
from decimal import Decimal as D
import hashlib
import io
import json
import os
from pathlib import Path

from research.jobs.replay_account_controls import replay, timestamp
from research.jobs.verify_spy_affordability import verify_ticker_routing, metrics

PAIRS = {
    'V2_SPY_TREND_CONT': ('SPY',),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('SPY',),
    'V2_SPY_AFTERNOON_FVG': ('SPY',),
    'V2_ORB_PULLBACK': ('TSLA',),
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('TSLA',),
    'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG': ('AMZN', 'TSLA'),
}
SOURCES = {
    'spy': ('spy_three_strategy_affordability_v1.json', 'spy_affordability_verified_account_v2.json',
            'spy_affordability_independent_verification_account_v2_ticker_routing', 'input_sha256'),
    'two_leg': ('two_leg_affordable_fixed142_v1.json', 'two_leg_affordable_verified_v1.json',
                'two_leg_affordable_independent_verification_v1', 'sources'),
    'displacement': ('displacement_affordable_native_v1.json', 'displacement_affordable_verified_v2.json',
                     'displacement_affordable_independent_verification_v2', 'fingerprints'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_verified(root, settings_path):
    """Require unchanged inputs and verifier code, not an unbound green flag."""
    loaded, fingerprints = {}, {}
    for family, (filename, proofname, protocol, field) in SOURCES.items():
        source, proofpath = root / filename, root / proofname
        proof = json.loads(proofpath.read_text())
        if proof.get('protocol') != protocol:
            raise ValueError('Unexpected verification protocol')
        bound = proof[field]
        for needed in (source, settings_path, Path(__file__).with_name('replay_account_controls.py')):
            if str(needed) not in bound:
                raise ValueError('Verification does not bind a required input')
        for path, fingerprint in bound.items():
            if sha(path) != fingerprint:
                raise ValueError('Verified source changed: ' + path)
            fingerprints[path] = fingerprint
        fingerprints[str(proofpath)] = sha(proofpath)
        data = json.loads(source.read_text())
        if not data.get('complete'):
            raise ValueError('Incomplete price experiment')
        loaded[family] = data
    return loaded, fingerprints


def sessions(path):
    with path.open() as stream:
        reader = csv.DictReader(stream)
        column = 'timestamp' if 'timestamp' in reader.fieldnames else 'time'
        return sorted({timestamp(r[column]).date().isoformat() for r in reader})


def normalize(data, arm):
    """Keep source identities and missing results. No per-strategy dedup gate."""
    rows = []
    for family, artifact in data.items():
        for r in artifact['rows']:
            if family == 'spy':
                sid, ticker, identity = r['strategy_id'], 'SPY', r['id']
                out, path = r[arm], r[arm + '_path']
                start = r['control']['entry_time']
                first = path[0] if path else None
            elif family == 'two_leg':
                sid, ticker, identity = r['strategy_id'], r['ticker'], r['date']
                out, path, first = r['outcomes'][arm], r['paths'][arm], r['selections'][arm]
                start = r['entry_time']
            elif family == 'displacement':
                sid, ticker, identity = 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG', r['ticker'], r['id']
                # Preserve the EXISTING structural exit, not the alternative timer.
                out, first = r['legs'][arm]['structural'], r['selections'][arm]
                path = [q for q in r['paths'][arm] if timestamp(q['time']) <= timestamp(out['exit_time'])]
                start = r['entry_time']
            else:
                raise ValueError('Unexpected source family')
            if sid not in PAIRS or ticker not in PAIRS[sid]:
                raise ValueError('Not an enabled native strategy/ticker pair')
            row = dict(id=family + '|' + str(identity), family=family, strategy_id=sid,
                       ticker=ticker, entry_time=start, status=out['status'], path=path)
            if out['status'] == 'priced':
                if not first or not path or path[0] != first or timestamp(first['time']) != timestamp(start):
                    raise ValueError('Missing original entry quote')
                if timestamp(path[-1]['time']) != timestamp(out['exit_time']):
                    raise ValueError('Missing original exit quote')
                row['trade'] = dict(id=row['id'], strategy_id=sid, ticker=ticker, contracts=1,
                    contract_symbol=first['contract'], entry_time=start, exit_time=out['exit_time'],
                    entry_price=first['ask'], entry_bid=first['bid'], entry_size=first['ask_size'],
                    exit_price=out['exit_bid'])
            rows.append(row)
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate normalized opportunity')
    return rows


def run_arm(rows, settings, calendar, friction):
    if not calendar or calendar != sorted(set(calendar)):
        raise ValueError('Common calendar must be nonempty, ordered and unique')
    days = set(calendar)
    selected = [r for r in rows if timestamp(r['entry_time']).date().isoformat() in days]
    priced = [r for r in selected if r['status'] == 'priced']
    trades = [r['trade'] for r in priced]
    if any(timestamp(t['exit_time']).date().isoformat() not in days for t in trades):
        raise ValueError('Exit outside common calendar')
    quotes = [dict(trade_id=r['id'], observed_at=q['time'], bid=q['bid']) for r in priced for q in r['path']]
    # Conflicting observations for the same instrument/minute must not depend
    # on which strategy's row happens to sort first.
    observed = {}
    for r in priced:
        for q in r['path']:
            key = (q['contract'], timestamp(q['time']))
            values = tuple(D(q[k]) for k in ('bid', 'ask', 'bid_size', 'ask_size'))
            if key in observed and observed[key] != values:
                raise ValueError('Conflicting shared-contract quote')
            observed[key] = values
    with contextlib.redirect_stdout(io.StringIO()):
        result = replay(trades, quotes, settings, fee_per_side=1.65, friction_per_side=friction,
                        settlement_sessions=calendar, ticker_routing=True,
                        routing_paper=settings['paper_trading'])
    verify_ticker_routing(trades, result)
    by_id = {r['id']: r for r in priced}
    gaps = [r['id'] for r in priced if any((timestamp(b['time'])-timestamp(a['time'])).total_seconds()>120
                                         for a, b in zip(r['path'], r['path'][1:]))]
    depth = [c['id'] for c in result['closed'] if D(by_id[c['id']]['path'][-1]['bid_size']) < c['quantity']]
    if (abs(sum(D(str(c['pnl'])) for c in result['closed'])-D(str(result['net_pnl'])))>D('.000001') or
            abs(sum(D(str(v)) for v in result['daily_pnl'].values())-D(str(result['net_pnl'])))>D('.000001') or
            result['open_at_end'] or result['max_open']>settings['max_concurrent_positions']):
        raise ValueError('Combined account does not reconcile')
    pairs = {}
    for sid, tickers in PAIRS.items():
        for ticker in tickers:
            subset = [r for r in selected if r['strategy_id']==sid and r['ticker']==ticker]
            ids = {r['id'] for r in subset}
            pairs[sid + '|' + ticker] = dict(
                retained_opportunities=len(subset), statuses=dict(Counter(r['status'] for r in subset)),
                closed=metrics(c['pnl'] for c in result['closed'] if c['id'] in ids),
                skips=dict(Counter(d['reason'] for d in result['decisions'] if d['id'] in ids and d['action']=='skip')),
                complete_opportunity_coverage=False,
                coverage_note='Native historical replay unavailable' if sid=='V2_ORB_PULLBACK' else
                    'Retained opportunities only; absence does not prove no setup')
    tied = Counter(timestamp(t['entry_time']).isoformat() for t in trades)
    result.update(common_calendar_start=calendar[0], common_calendar_end=calendar[-1],
        common_sessions=len(calendar), source_entries=len(rows), inside_calendar=len(selected),
        outside_calendar=len(rows)-len(selected), priced_entries=len(trades),
        inside_statuses=dict(Counter(r['status'] for r in selected)),
        by_pair=pairs, source_paths_with_gaps_over_120s=gaps, insufficient_exit_depth=depth,
        skip_counts=dict(Counter(d['reason'] for d in result['decisions'] if d['action']=='skip')),
        tied_entry_clocks={k:v for k,v in tied.items() if v>1},
        simulated_tie_break='Stable source identity; not reconstructed production scheduler order',
        all_six_acceptance=False, deployable=False,
        unresolved_price_evidence=bool(gaps or depth or len(priced)!=len(selected) or
                                      result['stale_mark_uses_at_entry'] or result['unresolved_emergency_exits']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('audit-root', 'settings', 'spy-bars', 'tsla-bars', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    data, fingerprints = load_verified(args.audit_root, args.settings)
    verified = json.loads(args.settings.read_text())
    if verified.get('all_checks_pass') is not True:
        raise ValueError('Settings have not passed broker reconciliation')
    calendar = sorted(set(sessions(args.spy_bars)) & set(sessions(args.tsla_bars)))
    for path in (args.spy_bars, args.tsla_bars, Path(__file__)):
        fingerprints[str(path)] = sha(path)
    scenarios = {f'{arm}_friction_{stress}': run_arm(normalize(data, arm), verified['risk_settings'], calendar, stress)
                 for arm in ('control', 'candidate') for stress in (0, .01, .05)}
    output = dict(protocol='enabled_available_common_calendar_account_v1', sources=fingerprints,
        all_six_acceptance=False, deployable=False, scenarios=scenarios,
        limitations=[
            'Five strategies have retained native opportunities; TSLA Opening-Range historical replay is missing',
            'AMZN has no retained opportunity in this window; its full no-setup coverage is not established',
            'Retained priced setups are not a complete historical scheduler/candidate stream',
            'Shared stock-data calendar bounds are fixed before account simulation, not chosen by profitability',
            'Frozen cheaper-contract experiments, not dynamically reranked contracts or approved changes',
            'Current settings, modeled costs, sampled minute bids and instantaneous hypothetical fills',
            'No untouched holdout or real-market recovery acceptance; no deployment authorization from this result'])
    fd = os.open(args.output, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
    print(json.dumps({k:{n:r[n] for n in ('ending_equity','pf','sampled_drawdown','longest_losing_streak',
        'max_open','inside_calendar','outside_calendar','skip_counts','unresolved_price_evidence','tied_entry_clocks')}
        for k,r in scenarios.items()}, indent=2))


if __name__ == '__main__':
    main()
