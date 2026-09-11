"""Prospective four-arm exit experiment; pure state, no order/network access.

Only explicitly stamped new research plays, not native trading behavior.
Reuse the frozen causal quote engine to keep missing data and fill rules equal.
"""
from copy import deepcopy

from strategy_health.option_profit_protection import initialize, advance

PROTOCOL = 'initial_premium_loss20_plus_spread_trail_v1'
LOSS_FRACTION = .20
ARMS = ('original', 'profit_trail', 'loss_only', 'loss_and_trail')
STRATEGY_ID = 'V2_SPY_TREND_CONT'
STATE_KEY = 'initial_loss_test'


def metadata(strategy_id):
    return {'initial_loss_protocol': PROTOCOL} if strategy_id == STRATEGY_ID else {}


def attach(state, *, strategy_id, meta, entry_at, ask, bid, minutes):
    if strategy_id != STRATEGY_ID or meta.get('initial_loss_protocol') != PROTOCOL:
        return state
    return {**state, STATE_KEY: start(entry_at, ask, bid, minutes=minutes)}


def bundle(state):
    value = state.get(STATE_KEY)
    return value if value and value.get('protocol') == PROTOCOL else None


def advance_capture(state, **kwargs):
    value = advance(state, **kwargs)
    extra = bundle(state)
    if extra:
        value[STATE_KEY] = step(extra, contract=kwargs['contract'], now=kwargs['now'],
                                quote=kwargs.get('quote'), allow_profit_arm=kwargs.get('allow_arm', True))
    return value


def needs_quotes(state):
    extra = bundle(state)
    return bool(extra and any(leg['status'] in ({'pending_quote'} if name == 'original' else {'collecting', 'pending_quote'})
                              for name, leg in outcomes(extra).items()))


def comparison(rows):
    from collections import Counter
    from strategy_health.authored_exit_summary import net_profit
    from strategy_health.exit_comparison import totals
    selected = [r for r in rows if bundle(r['state'])]
    if not selected:
        return None
    matched = {name: [] for name in ARMS}
    statuses = {name: Counter() for name in ARMS}
    for row in selected:
        legs = outcomes(bundle(row['state']))
        common = {key: row[key] for key in ('candidate_id', 'contract_symbol', 'entry_ask', 'entry_quote_at')}
        priced = {name: {**common, **leg} for name, leg in legs.items()}
        for name, leg in legs.items():
            statuses[name][leg['status']] += 1
        if all(net_profit(leg) is not None for leg in priced.values()):
            for name in ARMS:
                matched[name].append(priced[name])
    count = len(matched['original'])
    return dict(protocol=PROTOCOL, tracked=len(selected), paired_results=count,
                unpaired=len(selected)-count, statuses={k: dict(v) for k, v in statuses.items()},
                arms={k: totals(v) for k, v in matched.items()})


def start(entry_at, ask, bid, *, minutes=30):
    seed = initialize(entry_at, ask, bid, minutes=minutes)
    # An invalid entry must not gain valid stop state through this experiment.
    floor = ask * (1 - LOSS_FRACTION) if seed['trail']['status'] == 'collecting' else None
    loss_only, combined = deepcopy(seed), deepcopy(seed)
    loss_only['stop'] = combined['stop'] = floor
    return dict(protocol=PROTOCOL, entry_at=str(entry_at), entry_ask=ask,
                minutes=minutes, loss_floor=floor, baseline=seed,
                loss_only=loss_only, loss_and_trail=combined)


def step(state, *, contract, now, quote=None, allow_profit_arm=True):
    if state['protocol'] != PROTOCOL:
        raise ValueError('Unknown initial-loss protocol')
    out = deepcopy(state)
    args = dict(entry_at=state['entry_at'], ask=state['entry_ask'], minutes=state['minutes'],
                contract=contract, now=now, quote=quote)
    out['baseline'] = advance(state['baseline'], allow_arm=allow_profit_arm, **args)
    for name in ('loss_only', 'loss_and_trail'):
        # Always test the prior loss floor, even before a strategy's profit
        # objective. Suppress new profit-stop tightening below when requested.
        value = advance(state[name], allow_arm=True, **args)
        leg = value['trail']
        if leg.get('reason') == 'option_profit_trail':
            trigger = leg.get('trigger')
            if trigger and trigger['stop'] == state['loss_floor']:
                leg['reason'] = 'initial_loss_20pct'
        if name == 'loss_only' or not allow_profit_arm:
            if leg['status'] == 'collecting':
                value['stop'] = state['loss_floor'] if name == 'loss_only' else state[name]['stop']
                # Do not let peaks before the allowed objective arm a later
                # profit trail when objective eligibility changes.
                value['high_bid'] = None if name == 'loss_only' else state[name]['high_bid']
        out[name] = value
    return out


def outcomes(state):
    """Expose the four priced legs without manufacturing missing outcomes."""
    return dict(original=state['baseline']['control'], profit_trail=state['baseline']['trail'],
                loss_only=state['loss_only']['trail'], loss_and_trail=state['loss_and_trail']['trail'])


def active(state):
    return any(leg['status'] in {'collecting', 'pending_quote'} for leg in outcomes(state).values())
