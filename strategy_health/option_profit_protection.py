"""Frozen, sampled option-profit experiment. No orders and no promotion authority."""
from copy import deepcopy
from datetime import timedelta
import math
from statistics import median

from strategy_health.impulse_exit import et, executable_bid

STRATEGY_ID = 'V2_SPY_TREND_CONT'
PROTOCOL = 'option_bid_3spread_arm_2spread_trail_30m_v1'
VERSION = '2.1.0'
RECOVERY_STRATEGY_ID = 'V2_FAILED_OR_BREAK_VWAP_REVERSION'
RECOVERY_PROTOCOL = 'recovery_vwap_then_option_3spread_2spread_30m_v1'
ORB_STRATEGY_ID = 'V2_ORB_PULLBACK'
ORB_PROTOCOL = 'orb_option_3spread_arm_2spread_trail_90m_v1'
PROTOCOL_BY_STRATEGY = {STRATEGY_ID: PROTOCOL, RECOVERY_STRATEGY_ID: RECOVERY_PROTOCOL,
                        ORB_STRATEGY_ID: ORB_PROTOCOL}
VERSION_BY_STRATEGY = {STRATEGY_ID: VERSION, RECOVERY_STRATEGY_ID: VERSION, ORB_STRATEGY_ID: '2.0.0'}
MINUTES_BY_STRATEGY = {STRATEGY_ID: 30, RECOVERY_STRATEGY_ID: 30, ORB_STRATEGY_ID: 90}
# Frozen before forward outcomes: $0.65/side, $0.01/side slippage, 100 shares.
ROUND_TRIP_PRICE_COST = .033
MAX_GAP_SECONDS = 120


def metadata(strategy_id):
    protocol = PROTOCOL_BY_STRATEGY.get(strategy_id)
    return {'profit_protection_protocol': protocol} if protocol else {}


def initialize(entry_at, ask, bid, *, minutes=30):
    entry = et(entry_at)
    valid = (all(isinstance(v, (float, int)) and math.isfinite(v) for v in (ask, bid))
             and 0 <= bid <= ask and ask > 0
             and entry.replace(hour=9, minute=30, second=0, microsecond=0) <= entry
             and minutes in {30, 90}
             and entry + timedelta(minutes=minutes) <= entry.replace(hour=15, minute=55, second=0, microsecond=0))
    status = 'collecting' if valid else 'invalid_entry'
    return dict(control={'status': status}, trail={'status': status},
                spread=max(.01, ask-bid) if valid else None,
                last_bid_at=None, last_received_at=entry.isoformat(), quote_count=0,
                high_bid=None, stop=None)


def advance(state, *, entry_at, ask, contract, now, quote=None, allow_arm=True, minutes=30):
    """Causal state transition: test prior stop; price only a later exchange bid.

    Both calls and puts are long options: a higher premium is favorable.
    Quote gaps invalidate the path, but never erase the independent control.
    Receipt time is decision time: a historical exchange stamp cannot backdate
    when this sampled observer first knew that its trail had been crossed.
    """
    out = deepcopy(state)
    now, entry = et(now), et(entry_at)
    if minutes not in {30, 90}:
        raise ValueError('Unsupported frozen exit horizon')
    cap = entry + timedelta(minutes=minutes)
    for name in ('control', 'trail'):
        leg = out[name]
        if leg['status'] == 'collecting':
            if name == 'trail' and (min(now, cap)-et(out['last_received_at'])).total_seconds() > MAX_GAP_SECONDS:
                leg.update(status='missing_path', reason='quote_gap_over_120s')
            elif now >= cap:
                leg.update(status='pending_quote', decision_at=cap.isoformat(), reason=f'fixed_{minutes}m')
        if leg['status'] == 'pending_quote' and now > et(leg['decision_at'])+timedelta(seconds=60):
            leg['status'] = 'missing_quote'
    if quote is None or now <= entry:
        return out
    priced = executable_bid(quote, contract=contract,
                            decision_at=max(entry, now-timedelta(seconds=60)), received_at=now)
    if not priced:
        return out
    bid, stamp = priced
    if et(stamp) <= entry:
        return out
    # Spread-based decisions also require a fresh ask, not a stale other side.
    ask_priced = executable_bid(dict(quote, bid_date=quote.get('ask_date')),
                               contract=contract, decision_at=max(entry, now-timedelta(seconds=60)), received_at=now)
    for name in ('control', 'trail'):
        leg = out[name]
        if (leg['status'] == 'pending_quote' and et(stamp) > et(leg['decision_at'])
                and now <= et(leg['decision_at'])+timedelta(seconds=60)):
            leg.update(status='priced', bid=bid, bid_at=stamp, received_at=now.isoformat())
    if out['trail']['status'] != 'collecting' or not ask_priced:
        return out
    if out['last_bid_at'] and et(stamp) <= et(out['last_bid_at']):
        return out
    out.update(last_bid_at=stamp, last_received_at=now.isoformat(), quote_count=out['quote_count']+1)
    if not allow_arm:
        return out  # Pre-objective premium peaks cannot arm a later runner.
    previous_stop = out['stop']
    if previous_stop is not None and bid <= previous_stop:
        # One immutable diagnostic snapshot, not an extra quote request or fill.
        # Keep the crossing quote separate from the later executable quote so
        # research can distinguish detection overshoot from post-decision drift.
        out['trail'].update(status='pending_quote', decision_at=now.isoformat(), reason='option_profit_trail',
                            trigger=dict(evidence_version=1, bid=bid, ask=float(quote['ask']),
                                         bid_at=stamp, ask_at=ask_priced[1], received_at=now.isoformat(),
                                         stop=previous_stop, high_bid=out['high_bid'],
                                         previous_bid_at=state['last_bid_at'],
                                         previous_received_at=state['last_received_at']))
        return out  # Triggering quote cannot also fill this decision.
    out['high_bid'] = max(out['high_bid'] or bid, bid)
    if out['high_bid'] >= ask + ROUND_TRIP_PRICE_COST + 3*out['spread']:
        distance = 2*max(out['spread'], float(quote['ask'])-bid)
        out['stop'] = max(previous_stop if previous_stop is not None else -math.inf, out['high_bid']-distance)
    return out


def summary(samples, rows, strategy_id=STRATEGY_ID):
    from strategy_health.initial_loss_protection import comparison
    from strategy_health.authored_exit_summary import net_profit
    from strategy_health.exit_comparison import totals
    protocol = PROTOCOL_BY_STRATEGY[strategy_id]
    selected = [rows[s['candidate_id']] for s in samples if s['candidate_id'] in rows
                and rows[s['candidate_id']]['protocol'] == protocol]
    controls, trails, differences, days = [], [], [], set()
    statuses = {}
    for row in selected:
        for key in ('control', 'trail'):
            status = row['state'][key]['status']
            statuses[status] = statuses.get(status, 0)+1
        common = {k: row[k] for k in ('candidate_id', 'contract_symbol', 'entry_ask', 'entry_quote_at')}
        a, b = (dict(common, **row['state'][key]) for key in ('control', 'trail'))
        pa, pb = net_profit(a), net_profit(b)
        if pa is not None and pb is not None:
            controls.append(a)
            trails.append(b)
            differences.append(round(pb-pa, 2))
            days.add(et(row['entry_quote_at']).date().isoformat())
    return dict(protocol=protocol, minutes=MINUTES_BY_STRATEGY[strategy_id], tracked=len(selected), paired_results=len(controls),
                target_reached=sum(bool(r['state'].get('target_detected_at')) for r in selected),
                paired_days=len(days), unpaired=len(selected)-len(controls), statuses=statuses,
                control=totals(controls), trail=totals(trails),
                average_improvement=round(sum(differences)/len(differences), 2) if differences else None,
                median_improvement=round(median(differences), 2) if differences else None,
                initial_loss_comparison=comparison(selected))
