"""Reproduce aggregate September audit from the approved private local export."""
import argparse
import hashlib
import json
from pathlib import Path
from config.strategy_catalog import REVIEWED_STRATEGIES
from research.jobs.reconcile_september_paper_audit import reconcile, number, money
from research.jobs.verify_september_execution import verify_execution, recorded_quantity_account_scenario


def summarize(payload):
    versions = {sid: REVIEWED_STRATEGIES[sid].version for sid in payload['scope']['strategies']}
    result = reconcile(payload, versions)
    result.pop('leg_checks')
    result['broker_fill_verification'] = verify_execution(payload)
    result['fixed_quantity_5000_scenarios'] = [recorded_quantity_account_scenario(payload, cost=c) for c in ('0','1.30')]
    result['two_leg_existing_profit_trail_arming_check'] = []
    for t in payload['trades']:
        if t['strategy_id'] != 'V2_TSLA_TWO_LEG_TREND_PULLBACK':
            continue
        quotes = [q for q in payload['option_quotes'] if q['trade_id'] == t['id']]
        entries = [q for q in quotes if q['observation_kind'] == 'entry']
        marks = [q for q in quotes if q['observation_kind'] == 'mark' and q['bid'] is not None]
        if len(entries) != 1 or not marks:
            raise ValueError('missing arming-check evidence')
        entry = entries[0]
        spread = max(number('.01'), number(entry['ask'])-number(entry['bid']))
        # Frozen earlier research rule, not a newly optimized threshold.
        arm = number(entry['ask']) + number('.033') + 3*spread
        peak = max(number(q['bid']) for q in marks)
        result['two_leg_existing_profit_trail_arming_check'].append({
            'trade_id': t['id'], 'required_sampled_bid': str(arm),
            'highest_recorded_mark_bid': str(peak), 'would_arm_on_recorded_marks': peak >= arm,
            'caveat': 'Sampled observation times only; no exchange freshness/size proof or hypothetical fill claim.'})
    result['validation_assessment'] = 'Share with caveats: scoped ledger arithmetic and event consistency, not independent broker statement or live-profit proof.'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args=parser.parse_args()
    raw=args.input.read_bytes()
    result=summarize(json.loads(raw))
    result['source_sha256']=hashlib.sha256(raw).hexdigest()
    # Derived aggregates, exclusive-create: never overwrite a previous audit.
    with args.output.open('x') as output:
        json.dump(result,output,indent=2,allow_nan=False)
        output.write('\n')
    print(json.dumps({'saved_summary':str(args.output),
        'closed_positions':result['all_reconciled_completed_positions']['completed_positions'],
        'gross':result['all_reconciled_completed_positions']['gross'],
        'broker_checks':result['broker_fill_verification'],
        'profit_trail_arming':result['two_leg_existing_profit_trail_arming_check']}))

if __name__ == '__main__':
    main()
