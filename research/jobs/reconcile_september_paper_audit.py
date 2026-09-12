"""Offline reconciliation of the scoped audit export. Never imports broker code.

Recorded fill P&L remains gross. A separately labeled cost scenario is NOT a
broker fee reconciliation. Partial positions count once only after all legs
close. Missing versions stay in all-version history, not current-version proof.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
D = Decimal


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('missing or invalid numeric value')
    try:
        result = D(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid numeric value') from exc
    if not result.is_finite():
        raise ValueError('nonfinite numeric value')
    return result


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return result.replace(tzinfo=ET) if result.tzinfo is None else result.astimezone(ET)


def money(value):
    return str(value.quantize(D('.01')))


def metrics(positions, cost):
    gross = [p['pnl'] for p in positions]
    net = [p['pnl']-cost*p['quantity'] for p in positions]
    def summarize(values):
        gains = sum((x for x in values if x>0), D(0))
        losses = -sum((x for x in values if x<0), D(0))
        return dict(pnl=money(sum(values,D(0))), wins=sum(x>0 for x in values),
                    losses=sum(x<0 for x in values), breakeven=sum(x==0 for x in values),
                    profit_factor=money(gains/losses) if losses else 'no_losses' if gains else None)
    return dict(completed_positions=len(positions), gross=summarize(gross),
                cost_scenario=summarize(net))


def reconcile(payload, current_versions, round_trip_cost='1.30'):
    cost = number(round_trip_cost)
    if cost<0:
        raise ValueError('cost cannot be negative')
    scope = payload['scope']
    allowed = set(scope['strategies'])
    if scope['mode']!='paper':
        raise ValueError('paper audit only')
    trades = payload['trades']
    ids = [t['id'] for t in trades]
    if len(ids)!=len(set(ids)):
        raise ValueError('duplicate trade ids')
    candidates = {}
    for row in payload['candidates']:
        if row['candidate_id'] in candidates:
            raise ValueError('duplicate candidate ids')
        candidates[row['candidate_id']] = row
    issues, leg_checks, groups = [], [], defaultdict(list)
    realized = D(0)
    for trade in trades:
        tid = trade['id']
        if trade['paper']!=1 or trade['strategy_id'] not in allowed:
            raise ValueError('out-of-scope trade')
        date = stamp(trade['entry_time']).date().isoformat()
        if not scope['start']<=date<scope['end_exclusive']:
            raise ValueError('out-of-scope entry date')
        candidate = candidates.get(trade.get('candidate_id'))
        version = None
        if candidate:
            if (candidate['strategy_id'],candidate['ticker']) != (trade['strategy_id'],trade['ticker']):
                raise ValueError('candidate strategy/ticker mismatch')
            version = candidate.get('metadata',{}).get('strategy_version')
        check = dict(trade_id=tid, version=version, status=trade['status'],
                     recorded_pnl=None, recomputed_pnl=None, reconciled=False)
        if trade['status']=='closed':
            try:
                quantity = number(trade['contracts'])
                entry, exit = number(trade['entry_price']), number(trade['exit_price'])
                if quantity<=0 or quantity!=int(quantity) or entry<=0 or exit<0:
                    raise ValueError('invalid size or price')
                if stamp(trade['exit_time'])<stamp(trade['entry_time']):
                    raise ValueError('exit precedes entry')
                recorded = number(trade['realized_pnl'])
                computed = (exit-entry)*quantity*100
                realized += recorded
                check.update(recorded_pnl=money(recorded),recomputed_pnl=money(computed))
                if abs(recorded-computed)>D('.005'):
                    raise ValueError('recorded P&L differs from fill arithmetic')
                check['reconciled'] = True
                check['_pnl'],check['_quantity'] = recorded, quantity
            except (ValueError, TypeError, KeyError) as exc:
                issues.append(dict(trade_id=tid,reason=str(exc)))
        groups[trade.get('parent_trade_id') or tid].append((trade,check))
        leg_checks.append(check)
    completed, incomplete = [], []
    for root, legs in groups.items():
        if root not in [t['id'] for t,c in legs]:
            incomplete.append(dict(root_trade_id=root,reason='missing_parent'))
            continue
        if len({(t['strategy_id'],t['ticker'],t['contract_symbol']) for t,c in legs})!=1:
            incomplete.append(dict(root_trade_id=root,reason='inconsistent_partial_position'))
            continue
        if any(t['status']!='closed' for t,c in legs):
            incomplete.append(dict(root_trade_id=root,reason='still_open'))
            continue
        if any(not c['reconciled'] for t,c in legs):
            incomplete.append(dict(root_trade_id=root,reason='unreconciled_leg'))
            continue
        versions = {c['version'] for t,c in legs}
        completed.append(dict(root_trade_id=root, strategy_id=legs[0][0]['strategy_id'],
            ticker=legs[0][0]['ticker'], version=next(iter(versions)) if len(versions)==1 else None,
            pnl=sum((c['_pnl'] for t,c in legs),D(0)),
            quantity=sum((c['_quantity'] for t,c in legs),D(0))))
    by_strategy = {}
    for sid in sorted(allowed):
        positions = [p for p in completed if p['strategy_id']==sid]
        current = [p for p in positions if p['version'] is not None and p['version']==current_versions.get(sid)]
        by_strategy[sid] = dict(all_versions=metrics(positions,cost),
            current_version=current_versions.get(sid), current=metrics(current,cost),
            other_or_unidentified_positions=len(positions)-len(current))
    for check in leg_checks:
        check.pop('_pnl',None)
        check.pop('_quantity',None)
    return dict(scope=scope, issues=issues, incomplete_positions=incomplete,
                record_arithmetic_clean=not issues,
                finite_recorded_closed_leg_pnl=money(realized),
                cost_scenario_round_trip_per_contract=str(cost),
                cost_scenario_is_actual_fees=False,
                all_reconciled_completed_positions=metrics(completed,cost),
                strategies=by_strategy, leg_checks=leg_checks,
                broker_fill_verification='pending event/recovery-ledger reconciliation',
                quote_path_verification='pending; observed_at alone is not exchange freshness',
                account_equity_reconciliation='pending; scoped strategy P&L is not whole-account return')
