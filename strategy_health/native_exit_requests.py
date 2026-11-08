"""Read-only conversion of observed exit requests, never a native policy emulator.

Inputs must already be selected for one entry. These intents describe observed
requests; they do not prove complete decision coverage or broker execution.
"""
import hashlib
import json
from datetime import datetime

from strategy_health.paired_exit_accounting import Intent, clock, quantity


def context_hash(context):
    if isinstance(context,str): context=json.loads(context)
    if not isinstance(context,dict) or not context.get('strategy_version'):
        raise ValueError('missing_entry_policy_context')
    return hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def observed_intents(entry, events, *, frozen_context_hash):
    """Return native requests as hypothetical fill intents, rejecting divergence.

    Repeated requests for the same outstanding quantity/reason are retries, not
    additional sales. A broker partial fill can make the remaining size diverge
    from the hypothetical branch; reject that case instead of inventing fills.
    The caller must separately verify decision/capture coverage and policy pins.
    """
    entry.scope.validate();clock(entry.filled_at);quantity(entry.contracts)
    if not frozen_context_hash: raise ValueError('missing_frozen_policy_context')
    seen={}; event_ids={}; requests=[]
    for event in events:
        if event.get('stage')!='exit_order_request': continue
        if event.get('evidence_type')!='native_decision_observation_not_fill':
            raise ValueError('not_native_request_evidence')
        trade=event.get('trade') or {}
        scope=entry.scope
        if (str(trade.get('id'))!=str(entry.trade_id) or trade.get('broker_account_id')!=scope.account
                or event.get('mode')!=scope.mode or trade.get('strategy_id')!=scope.strategy
                or trade.get('ticker')!=scope.ticker or trade.get('contract_symbol')!=entry.contract):
            raise ValueError('native_request_scope_mismatch')
        context=trade.get('strategy_context_json')
        if isinstance(context,str): context=json.loads(context)
        if not isinstance(context,dict) or context.get('strategy_version')!=scope.version:
            raise ValueError('native_request_version_mismatch')
        if context_hash(context)!=frozen_context_hash: raise ValueError('entry_policy_context_changed')
        snap=event.get('snapshot') or {}
        if snap.get('complete') is not True or snap.get('issues'):
            raise ValueError('incomplete_exit_request_snapshot')
        data=snap.get('data') or {};order=data.get('order') or {}
        action=data.get('action_id');eid=event.get('event_id')
        if not action or not eid or not event.get('cycle_id'): raise ValueError('missing_request_identity')
        if eid in event_ids and event_ids[eid]!=event: raise ValueError('conflicting_event_identity')
        event_ids[eid]=event
        if action in seen:
            if seen[action]!=event: raise ValueError('conflicting_request_identity')
            continue
        seen[action]=event
        at=clock(datetime.fromisoformat(event['recorded_at']))
        if at<entry.filled_at: raise ValueError('exit_request_before_entry')
        if (order.get('symbol')!=entry.contract or order.get('side')!='sell'
                or order.get('position_intent')!='sell_to_close'):
            raise ValueError('not_matching_close_request')
        qty=quantity(order.get('qty'));remaining=quantity(data.get('remaining_contracts'))
        reason=(order.get('order_context') or {}).get('exit_reason')
        if not isinstance(reason,str) or not reason.strip() or qty>remaining:
            raise ValueError('invalid_exit_request')
        requests.append((at,eid,qty,remaining,reason,action))
    requests.sort()
    left=entry.contracts;intents=[];previous=None;retry_ids=[];later_ids=[]
    for at,eid,qty,remaining,reason,action in requests:
        signature=(qty,remaining,reason)
        if left==0:
            later_ids.append(eid);continue
        if signature==previous:
            retry_ids.append(eid);continue
        if remaining!=left: raise ValueError('actual_shadow_quantity_divergence')
        intents.append(Intent(at,qty,reason,eid))
        left-=qty;previous=signature
    if not intents: raise ValueError('missing_native_exit_requests')
    if left: raise ValueError('incomplete_native_exit_requests')
    return {'intents':intents,'retry_request_ids':retry_ids,
            'requests_after_hypothetical_close':later_ids,
            'evidence_kind':'observed_native_requests_not_fills',
            'decision_coverage_verified':False,'frozen_context_hash':frozen_context_hash}
