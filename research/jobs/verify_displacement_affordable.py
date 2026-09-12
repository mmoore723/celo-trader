"""Independent retained-price checks and current-account stress diagnostic."""
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

SID = 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'


def at(v):
    stamp = datetime.fromisoformat(v)
    if stamp.tzinfo is None:
        raise ValueError('Naive evidence clock')
    return stamp


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def metrics(values):
    wins = sum((v for v in values if v>0), D(0))
    losses = -sum((v for v in values if v<0), D(0))
    return dict(count=len(values), net=float(sum(values,D(0))), wins=sum(v>0 for v in values),
                pf=float(wins/losses) if losses else None)


def validate(data, assessment):
    if not data['complete'] or data['protocol']!='displacement_native_fixed080_142_contract_comparison_v1':
        raise ValueError('Incomplete or wrong experiment')
    originals={r['candidate_id']:r for r in assessment['rows'] if r['profile']=='reviewed_bounds' and r['native'] and r['independent']}
    if len(data['rows'])!=len(originals) or {r['id'] for r in data['rows']}!=set(originals):
        raise ValueError('Native entry cohort changed')
    for row in data['rows']:
        old=originals[row['id']]
        start=at(old['entry_snapshot_at'])
        if row['ticker']!=old['ticker'] or at(row['entry_time'])!=start:
            raise ValueError('Entry identity changed')
        for name in ('control','candidate'):
            if set(row['legs'][name])!={'structural','timer'}:
                raise ValueError('Missing exit comparison leg')
            first=row['selections'][name]
            path=row['paths'][name]
            if first is None:
                if name=='control' or path or any(v['status']!='no_contract' for v in row['legs'][name].values()):
                    raise ValueError('Missing selection not preserved')
                continue
            symbol=re.fullmatch(re.escape(row['ticker'])+r'\s+(\d{6})C(\d{8})',first['contract'])
            if not symbol:
                raise ValueError('Wrong contract direction')
            expiry=datetime.strptime(symbol[1],'%y%m%d').date()
            ask,bid=D(first['ask']),D(first['bid'])
            lower,upper=(D('1.5'),D('2.5')) if name=='control' else (D('.8'),D('1.42'))
            if not (lower<=ask<=upper and 0<=(expiry-start.date()).days<=7 and
                    D(symbol[2])/1000>D(str(old['stock_reference'])) and (ask-bid)/((ask+bid)/2)<=D('.08')):
                raise ValueError('Profile bounds changed')
            times=[at(q['time']) for q in path]
            if not times or times!=sorted(set(times)) or times[0]!=start or path[0]!=first:
                raise ValueError('Missing or duplicate entry/path')
            for q in path:
                nums=[D(q[k]) for k in ('bid','ask','bid_size','ask_size')]
                stamp=at(q['time'])
                end=max(at(v['quote_at']) for v in old['legs'].values())
                if not all(n.is_finite() and n>0 for n in nums) or nums[0]>nums[1] or q['contract']!=first['contract'] or not start<=stamp<=end or stamp.second or stamp.microsecond:
                    raise ValueError('Invalid retained quote')
            if name=='control' and (first['contract']!=old['contract'].strip() or
                    ask!=D(old['entry_ask']) or bid!=D(old['entry_bid'])):
                raise ValueError('Original control entry changed')
            for leg, outcome in row['legs'][name].items():
                wanted=at(old['legs'][leg]['quote_at'])
                if at(outcome['exit_time'])!=wanted or wanted!=at(old['legs'][leg]['decision_at'])+timedelta(minutes=1):
                    raise ValueError('Exit decision/availability changed')
                q=next((q for q in path if at(q['time'])==wanted),None)
                if q is None:
                    if name=='control' or outcome['status']!='missing_exit':
                        raise ValueError('Missing exit invented')
                    continue
                expected=(D(q['bid'])-ask)*100-D('3.30')
                if outcome['status']!='priced' or D(outcome['exit_bid'])!=D(q['bid']) or D(outcome['net'])!=expected:
                    raise ValueError('Price or cost mismatch')
                if name=='control' and expected!=D(str(old['legs'][leg]['net_pnl_one_contract'])):
                    raise ValueError('Original control outcome changed')


def account(data, settings, sessions):
    output={}
    for name in ('control','candidate'):
        for leg in ('structural','timer'):
            trades,quotes=[],[]
            gaps=[]
            for row in data['rows']:
                first=row['selections'][name]; outcome=row['legs'][name][leg]
                if outcome['status']!='priced':
                    continue
                path=[q for q in row['paths'][name] if at(q['time'])<=at(outcome['exit_time'])]
                if any((at(b['time'])-at(a['time'])).total_seconds()>120 for a,b in zip(path,path[1:])):
                    gaps.append(row['id'])
                trades.append(dict(id=row['id'],ticker=row['ticker'],strategy_id=SID,contracts=1,
                    contract_symbol=first['contract'],entry_time=row['entry_time'],exit_time=outcome['exit_time'],
                    entry_price=first['ask'],entry_bid=first['bid'],entry_size=first['ask_size'],exit_price=outcome['exit_bid']))
                quotes.extend(dict(trade_id=row['id'],observed_at=q['time'],bid=q['bid']) for q in path)
            for stress in (0,.01,.05):
                with contextlib.redirect_stdout(io.StringIO()):
                    result=replay(trades,quotes,settings,fee_per_side=1.65,friction_per_side=stress,
                                  settlement_sessions=sessions,ticker_routing=True,routing_paper=settings['paper_trading'])
                result['source_entries']=len(data['rows'])
                result['priced_entries']=len(trades)
                result['source_paths_with_gaps_over_120s']=gaps
                result['skip_counts']=dict(Counter(r['reason'] for r in result['decisions'] if r['action']=='skip'))
                by_id={r['id']:r for r in data['rows']}
                result['insufficient_exit_depth']=[r['id'] for r in result['closed'] if D(next(q for q in by_id[r['id']]['paths'][name]
                    if at(q['time'])==at(by_id[r['id']]['legs'][name][leg]['exit_time']))['bid_size'])<r['quantity']]
                if abs(sum(D(str(c['pnl'])) for c in result['closed'])-D(str(result['net_pnl'])))>D('.000001'):
                    raise ValueError('Account sum mismatch')
                output[f'{name}_{leg}_{stress}']=result
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('input','assessment','settings','bars','output'):
        parser.add_argument('--'+n,type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text()); assessment=json.loads(args.assessment.read_text())
    if data['input_sha256']!=sha(args.assessment) or data['code_sha256']!=sha(Path(__file__).with_name('replay_displacement_affordable.py')):
        raise ValueError('Input/producer fingerprint changed')
    if data['helper_sha256']!=sha(Path(__file__).with_name('replay_spy_affordable_contracts.py')):
        raise ValueError('Shared quote/checkpoint helper changed')
    validate(data,assessment)
    verified=json.loads(args.settings.read_text())
    if not verified['all_checks_pass']:
        raise ValueError('Settings not verified')
    with args.bars.open() as source:
        reader=csv.DictReader(source)
        column='timestamp' if 'timestamp' in reader.fieldnames else 'time'
        sessions=sorted({row[column][:10] for row in reader})
    summary={f'{name}_{leg}':metrics([D(row['legs'][name][leg]['net']) for row in data['rows']
                if row['legs'][name][leg]['status']=='priced']) for name in ('control','candidate') for leg in ('structural','timer')}
    effects={}
    for leg in ('structural','timer'):
        pairs=[(D(r['legs']['control'][leg]['net']),D(r['legs']['candidate'][leg]['net']))
               for r in data['rows'] if r['legs']['candidate'][leg]['status']=='priced']
        effects[leg]=dict(paired=len(pairs),lost_winners=sum(a>0 and b<=0 for a,b in pairs),
            change_on_control_winners=float(sum((b-a for a,b in pairs if a>0),D(0))),
            change_on_control_losers=float(sum((b-a for a,b in pairs if a<0),D(0))))
    output=dict(protocol='displacement_affordable_independent_verification_v2',
        fingerprints={str(p):sha(p) for p in (args.input,args.assessment,args.settings,args.bars,Path(__file__),
            Path(__file__).with_name('replay_account_controls.py'))},
        summary=summary,winner_effects=effects,account=account(data,verified['risk_settings'],sessions),
        limitations=['Seven frozen native setups only; not all six strategies or independent holdout',
            'Same saved stock decisions; existing structural exit unchanged, not newly optimized',
            'Fixed initial premium cap, not contract reselection against evolving account equity',
            'Sampled minute bids, instantaneous fills and displayed sizes; not broker-fill proof',
            'Current settings and supplied-session settlement; other scheduler/entry gates not replayed'])
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as destination:
        json.dump(output,destination,indent=2,allow_nan=False)
    print(json.dumps(dict(summary=summary,account={k:{n:r[n] for n in ('ending_equity','pf','sampled_drawdown',
        'longest_losing_streak','max_open','skip_counts','source_paths_with_gaps_over_120s','insufficient_exit_depth')}
        for k,r in output['account'].items()}),indent=2))


if __name__=='__main__':
    main()
