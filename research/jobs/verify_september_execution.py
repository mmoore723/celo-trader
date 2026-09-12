"""Validate local event evidence; never call a broker or infer hypothetical fills."""
from collections import defaultdict
from decimal import Decimal
from research.jobs.reconcile_september_paper_audit import number, money, stamp


def verify_execution(payload):
    events = {}
    for event in payload['broker_events']:
        previous = events.get(event['id'])
        if previous is not None and previous != event:
            raise ValueError('conflicting event id')
        events[event['id']] = event
    issues, sides_verified = [], 0
    for trade in payload['trades']:
        if trade['status'] != 'closed':
            continue
        for side, prefix in [('buy', 'entry'), ('sell', 'exit')]:
            order = trade.get(prefix + '_order_id')
            fills = [e for e in events.values() if order and e['order_id'] == order
                     and e['event_type'] == 'filled']
            summaries = [e for e in events.values() if e['linked_trade_id'] == trade['id']
                         and e['side'] == side and e['event_type'] == 'execution_summary']
            reason = None
            if not fills or len(summaries) != 1:
                reason = 'missing or ambiguous fill evidence'
            else:
                for event in fills + summaries:
                    if (event['side'] != side or event['status'] != 'filled'
                        # Broker-only filled events may omit strategy_id. Their
                        # exact order/contract/trade links plus the separately
                        # required strategy-bearing summary establish identity.
                        or (event['strategy_id'] != trade['strategy_id']
                            and not (event['event_type'] == 'filled'
                                     and event['strategy_id'] in (None, '')))
                        or event['contract_symbol'] != trade['contract_symbol']
                        or event['linked_trade_id'] != trade['id']
                        or number(event['filled_qty']) != number(trade['contracts'])
                        or number(event['fill_price']) != number(trade[prefix + '_price'])):
                        reason = 'fill identity, quantity or price mismatch'
            if reason:
                issues.append({'trade_id': trade['id'], 'side': side, 'reason': reason})
            else:
                sides_verified += 1
    return {'unique_events': len(events), 'verified_entry_or_exit_sides': sides_verified,
            'issues': issues, 'source': 'recorded broker events, not an independent broker statement',
            'repeated_filled_events_are_not_additional_trades': True}


def recorded_quantity_account_scenario(payload, initial='5000', cost='1.30'):
    """Cash-constrained, fixed recorded sizes; not a bot-sizing or MTM backtest."""
    cash = number(initial)
    cost = number(cost)
    realized = Decimal(0)
    peak = cash
    maximum_drawdown = Decimal(0)
    committed = Decimal(0)
    max_committed = Decimal(0)
    active = set()
    max_open = 0
    insufficient = []
    timeline, daily = [], defaultdict(lambda: Decimal(0))
    trades = payload['trades']
    if any(t.get('parent_trade_id') or t['status'] != 'closed' for t in trades):
        raise ValueError('scenario requires whole closed positions')
    for t in trades:
        timeline.extend([(stamp(t['entry_time']), 1, t), (stamp(t['exit_time']), 0, t)])
    for at, entry, t in sorted(timeline, key=lambda x: (x[0], x[1], x[2]['id'])):
        qty = number(t['contracts'])
        premium = number(t['entry_price']) * qty * 100
        if entry:
            if t['id'] in active:
                raise ValueError('duplicate position entry')
            needed = premium + cost * qty / 2
            if needed > cash:
                insufficient.append(t['id'])
            cash -= needed
            committed += premium
            active.add(t['id'])
            max_open = max(max_open, len(active))
            max_committed = max(max_committed, committed)
        else:
            if t['id'] not in active:
                raise ValueError('exit without entry')
            cash += number(t['exit_price']) * qty * 100 - cost * qty / 2
            committed -= premium
            active.remove(t['id'])
            pnl = (number(t['exit_price']) - number(t['entry_price'])) * qty * 100 - cost * qty
            daily[at.date().isoformat()] += pnl
            realized += pnl
            marked_at_closed_pnl_only = number(initial) + realized
            peak = max(peak, marked_at_closed_pnl_only)
            maximum_drawdown = max(maximum_drawdown, peak - marked_at_closed_pnl_only)
    return {'initial': initial, 'final_cash': money(cash), 'round_trip_cost_per_contract': str(cost),
            'daily_closed_pnl': {k: money(v) for k, v in sorted(daily.items())},
            'closed_pnl_peak_to_trough': money(maximum_drawdown),
            'maximum_concurrent_premium': money(max_committed), 'maximum_open_positions': max_open,
            'insufficient_cash_trade_ids': insufficient,
            'limitations': 'Fixed recorded sizes; excludes open-position mark-to-market, buying-power rules, settlement, other strategies and actual account fees. Not a production risk-limit simulation.'}
