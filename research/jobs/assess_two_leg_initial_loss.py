"""Independent stop-decision audit, fixed gates and cash-constrained account model."""
import argparse
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from statistics import median

from research.jobs.replay_two_leg_initial_loss import PROTOCOL, at, number, compare

D=Decimal


def check_leg(actual, expected, ask):
    for key,value in expected.items():
        if actual.get(key)!=value:
            raise ValueError(f'Independent exit reconstruction differs: {key}')
    if expected['status']=='priced':
        pnl=(number(expected['bid'])-ask)*100-D('3.30')
        if number(actual['net'])!=pnl:
            raise ValueError('Exit cost arithmetic differs')
        if abs(number(actual['return_pct'])-pnl/(ask*100+D('1.65'))*100)>D('.000000001'):
            raise ValueError('Exit return arithmetic differs')
    elif any(k in actual for k in ('net','bid','exit_time')):
        raise ValueError('Missing result contains invented price')


def independently_verify(row, baseline):
    """Reconstruct first crossing directly from retained source snapshots."""
    for key in ('date','contract','entry_time'):
        if row[key]!=baseline[key]: raise ValueError('Entry identity changed')
    ask=number(baseline['entry_ask']);start=at(baseline['entry_time'])
    if number(row['entry_ask'])!=ask or number(row['entry_bid'])!=number(baseline['entry_bid']):
        raise ValueError('Entry prices changed')
    end=start+timedelta(minutes=90)
    qs=row['snapshots']
    times=[at(q['time']) for q in qs]
    if times!=sorted(set(times)) or not times or times[0]!=start:
        raise ValueError('Missing, duplicate or unsorted snapshots')
    for q,t in zip(qs,times):
        if (q['contract']!=baseline['contract'] or not start<=t<=end+timedelta(seconds=60)
            or t.second or t.microsecond or not 0<number(q['bid'])<=number(q['ask'])<1000000
            or min(number(q['bid_size']),number(q['ask_size']))<=0):
            raise ValueError('Invalid retained source snapshot')
    if number(qs[0]['ask'])!=ask or number(qs[0]['bid'])!=number(baseline['entry_bid']):
        raise ValueError('Entry source quote differs')
    def expected(decision,reason):
        following=[q for q in qs if decision<at(q['time'])<=decision+timedelta(seconds=60)]
        v={'status':'missing_quote','decision_at':decision.isoformat(),'reason':reason}
        if following:
            v.update(status='priced',bid=following[0]['bid'],exit_time=following[0]['time'])
        return v
    fixed=expected(end,'fixed_90m')
    if baseline['status']=='priced':
        if (fixed['status']!='priced' or number(fixed['bid'])!=number(baseline['exit_bid'])
                or at(fixed['exit_time'])!=at(baseline['exit_time'])):
            raise ValueError('Independent baseline exit mismatch')
    elif baseline['status']!='missing_exit' or fixed['status']!='missing_quote':
        raise ValueError('Independent baseline missingness mismatch')
    check_leg(row['control'],fixed,ask)
    crossing=None;gap=False;previous=start
    for q,t in zip(qs[1:],times[1:]):
        if (min(t,end)-previous).total_seconds()>120:
            gap=True;break
        if t>=end: break
        if number(q['bid'])<=ask*D('0.80'):
            crossing=q;break
        previous=t
    if crossing:
        wanted=expected(at(crossing['time']),'initial_loss_20pct')
        if (number(row['variant']['trigger_bid'])!=number(crossing['bid'])
                or number(row['variant']['floor'])!=ask*D('.80')):
            raise ValueError('Trigger evidence differs')
    elif gap or (end-previous).total_seconds()>120:
        wanted={'status':'missing_path','reason':'quote_gap_over_120s'}
    else:
        wanted=fixed
    check_leg(row['variant'],wanted,ask)


def account(rows, arm, initial='5000'):
    """One-contract fixed-policy cash book; no optimization or reinvested sizing."""
    cash=number(initial);peak=cash;drawdown=D(0);accepted=[];skips=[]
    last_exit=None;max_premium=D(0)
    sampled_peak=cash;sampled_dd=D(0);worst_trade_return=None
    for r in sorted(rows,key=lambda r:at(r['entry_time'])):
        if r[arm]['status']!='priced':
            skips.append({'date':r['date'],'reason':'missing_outcome'});continue
        if last_exit is not None and at(r['entry_time'])<last_exit:
            raise ValueError('Overlapping cohort requires portfolio book')
        cost=number(r['entry_ask'])*100+D('1.65')
        if cost>cash:
            skips.append({'date':r['date'],'reason':'insufficient_cash'});continue
        max_premium=max(max_premium,number(r['entry_ask'])*100)
        # Liquidation-value samples while actually holding this arm. Include
        # modeled exit friction, never later prices after an early exit.
        exit_time=at(r[arm]['exit_time'])
        for q in r['snapshots']:
            if at(r['entry_time'])<=at(q['time'])<=exit_time:
                liquidation=cash-cost+number(q['bid'])*100-D('1.65')
                sampled_peak=max(sampled_peak,liquidation)
                sampled_dd=max(sampled_dd,sampled_peak-liquidation)
        trade_return=number(r[arm]['net'])/cost*100
        worst_trade_return=trade_return if worst_trade_return is None else min(worst_trade_return,trade_return)
        cash+=number(r[arm]['net']);peak=max(peak,cash);drawdown=max(drawdown,peak-cash)
        sampled_peak=max(sampled_peak,cash);sampled_dd=max(sampled_dd,sampled_peak-cash)
        last_exit=at(r[arm]['exit_time']);accepted.append(r['date'])
    return dict(initial=initial,final_cash=str(cash),accepted=len(accepted),accepted_dates=accepted,
                skipped=skips,closed_pnl_drawdown=str(drawdown),maximum_entry_premium=str(max_premium),
                sampled_liquidation_drawdown=str(sampled_dd),worst_completed_trade_return_pct=str(worst_trade_return),
                assumptions='One contract; no size compounding, settlement or broker buying-power rules. Liquidation drawdown uses retained minute samples, not all intraminute moves. Threshold is not a guaranteed loss cap.')


def verify_aggregate_arithmetic(rows, summary):
    paired=sorted((r for r in rows if r['control']['status']==r['variant']['status']=='priced'),
                  key=lambda r:at(r['entry_time']))
    for arm in ('control','variant'):
        values=[(number(r[arm]['bid'])-number(r['entry_ask']))*100-D('3.30') for r in paired]
        gains=sum((v for v in values if v>0),D(0));losses=-sum((v for v in values if v<0),D(0))
        supplied=summary[arm]
        balance=peak=drawdown=D(0)
        for value in values:
            balance+=value;peak=max(peak,balance);drawdown=max(drawdown,peak-balance)
        if (supplied['count']!=len(values) or supplied['wins']!=sum(v>0 for v in values)
                or number(supplied['net'])!=sum(values,D(0)) or number(supplied['drawdown'])!=drawdown):
            raise ValueError('Independent aggregate arithmetic differs')
        expected_pf=str(gains/losses) if losses else ('no_losses' if gains else None)
        if supplied['pf']!=expected_pf:raise ValueError('Independent PF differs')


def assess(report, baseline):
    entries=[r for r in baseline['rows'] if r['status'] in ('priced','missing_exit')]
    if (report.get('protocol')!=PROTOCOL or not report.get('complete') or not baseline.get('complete')
            or report['entries']!=len(entries) or len(report['rows'])!=len(entries)):
        raise ValueError('Incomplete or wrong-protocol study; no final assessment')
    if report['coverage']!=dict(Counter(r['status'] for r in baseline['rows'])):
        raise ValueError('Source coverage changed')
    for r,b in zip(report['rows'],entries): independently_verify(r,b)
    all_results=compare(report['rows'])
    if report['summary']!=all_results: raise ValueError('Summary mismatch')
    verify_aggregate_arithmetic(report['rows'],all_results)
    partitions={name:compare([r for r in report['rows'] if (r['date']<'2026-05-19')==early])
                for name,early in [('before_may19',True),('from_may19',False)]}
    a,b=all_results['control'],all_results['variant']
    gates={'paired_count':all_results['paired']>=30,'no_unpaired':all_results['unpaired']==0,
           'pf_goal':b['pf'] not in (None,'no_losses') and number(b['pf'])>=D('1.5'),
           'positive_net':number(b['net'])>0,
           'positive_median':b['median_return'] is not None and number(b['median_return'])>0,
           'higher_net':number(b['net'])>number(a['net']),
           'median_change':all_results['median_change'] is not None and number(all_results['median_change'])>=0,
           'drawdown_no_worse':number(b['drawdown'])<=number(a['drawdown']),
           'date_partitions':all(p['paired']>=10 and number(p['variant']['net'])>=number(p['control']['net'])
                                 for p in partitions.values())}
    return dict(summary=all_results,partitions=partitions,gates=gates,
                verdict='development_candidate_only' if all(gates.values()) else 'does_not_pass_frozen_improvement_test',
                accounts={k:account(report['rows'],k) for k in ('control','variant')},
                limitations=['Previously inspected historical dates, not untouched forward validation.',
                    'Verifier reconstructs decisions from retained source snapshots, not a second full archive read.',
                    'Sampled minute-end BBO does not prove tick-level fills or broker receipt latency.',
                    'Missing outcomes never become zero-profit results.'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('report','baseline','plan','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    raw=args.report.read_bytes();report=json.loads(raw);base_raw=args.baseline.read_bytes()
    if report['baseline_sha256']!=hashlib.sha256(base_raw).hexdigest(): raise ValueError('Baseline changed')
    if report['plan_sha256']!=hashlib.sha256(args.plan.read_bytes()).hexdigest(): raise ValueError('Plan changed')
    runner=Path(__file__).with_name('replay_two_leg_initial_loss.py')
    if report['code_sha256']!=hashlib.sha256(runner.read_bytes()).hexdigest(): raise ValueError('Runner changed')
    out=assess(report,json.loads(base_raw));out['report_sha256']=hashlib.sha256(raw).hexdigest()
    out['assessor_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as target:json.dump(out,target,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in out.items() if k!='accounts'},indent=2))


if __name__=='__main__':main()
