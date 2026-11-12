"""Exact recorded broker-position controls. Never infer an old exit from a name."""
import json
from hashlib import sha256
from collections import defaultdict
from strategy_health.premium_rules import FEE, clock


def baseline_spec(settings, sid, ticker, version):
    from config.runtime_exit_review import REVISION
    from config.research_order_specs import SPECS
    from config.research_pair_policy import selected
    selection=selected(settings,sid,ticker,version) if sid in SPECS else None
    policy_settings={k:v for k,v in settings.items() if any(word in k.lower() for word in
        ('risk','stop','exit','trailing','profit','loss','session','premium_exit'))}
    body=dict(strategy=sid,ticker=ticker,version=version,runtime=REVISION,
              policy_settings_digest=sha256(json.dumps(policy_settings,sort_keys=True,default=str).encode()).hexdigest(),
              selected_test_policy=selection,scope='native exits plus mandatory account and session protection')
    body['fingerprint']=sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    return body


def recorded_positions(conn, *, account, mode, sid, ticker, version, expected):
    """A position includes its closed partial rows, never counts them as new entries."""
    rows=[dict(r) for r in conn.execute('SELECT * FROM trades WHERE broker_account_id=? AND paper=? AND strategy_id=? AND ticker=? ORDER BY entry_time,id',
                                       (account,int(mode=='paper'),sid,ticker))]
    by_id={r['id']:r for r in rows}; groups=defaultdict(list)
    for row in rows:
        root=row; seen=set()
        while root.get('parent_trade_id') in by_id:
            if root['id'] in seen: raise ValueError('cyclic_partial_trade_history')
            seen.add(root['id']);root=by_id[root['parent_trade_id']]
        groups[root['id']].append(row)
    samples=[]; completed=[]
    for root_id,legs in groups.items():
        root=by_id[root_id]
        try: context=json.loads(root.get('strategy_context_json') or '{}')
        except (ValueError,TypeError): context={}
        if context.get('strategy_version')!=version:
            continue
        quantity=sum(r['contracts'] for r in legs)
        entry=root.get('entry_fill_time') or root['entry_time']
        problem=None
        if context.get('premium_baseline')!=expected:
            problem='entry_frozen_current_policy_not_recorded'
        if any(not r.get('entry_order_id') or not r.get('entry_fill_time') for r in legs):
            problem='entry_fill_identity_or_time_missing'
        if any(r['contract_symbol']!=root['contract_symbol'] or abs(r['entry_price']-root['entry_price'])>1e-8 for r in legs):
            problem='partial_entry_prices_or_contracts_differ'
        sample=dict(candidate_id=str(root_id),observed_at=entry,entry_quote_at=entry,
            entry_contract=root['contract_symbol'],entry_ask=root['entry_price'],quantity=quantity,
            capture_origin='broker_trade',actual_entry=True,input_problem=problem,native_legs=[])
        if all(r['status']=='closed' for r in legs):
            if any(not r.get('exit_order_id') or not r.get('exit_fill_time') or r.get('exit_price') is None for r in legs):
                sample['input_problem']='exit_fill_identity_or_time_missing'
            else:
                actual=[]
                for r in legs:
                    actual.append(dict(at=r['exit_fill_time'],quantity=r['contracts'],
                        net=(r['exit_price']-r['entry_price'])*100*r['contracts']-2*FEE*r['contracts'],
                        reason=r['exit_reason'],order_id=r['exit_order_id'],price=r['exit_price']))
                sample['native_legs']=actual
                completed.append(dict(id=str(root_id),entry_at=entry,
                    exit_at=max(actual,key=lambda l:clock(l['at']))['at'],pnl=sum(l['net'] for l in actual)))
        samples.append(sample)
    return samples,completed
