"""Pure exit transitions for the separate expiration study.

The structural decisions reuse the production authored-exit evaluators. This
module never reads a broker, changes a primary result, or places an order.
"""
from copy import deepcopy
from datetime import timedelta
import math

import pandas as pd

from config.strategy_catalog import REVIEWED_STRATEGIES
from database.research_exits import EXIT_REASONS
from strategy_health.exit_protocols import PROTOCOLS, SUPPORTED_PROTOCOL_PAIRS, first_exit
from strategy_health import context_orb_exit, context_vwap_exit, squeeze_exit
from strategy_health.impulse_exit import et, executable_bid
from strategy_health.authored_exit_summary import net_profit
from trading.expiration_study_selection import PROFILE, PROFILES

# These five timers ARE the authored exits, not generic substitute checkpoints.
TIMED = {
    'V2_ORB_PULLBACK': 90,
    'V2_SPY_TREND_CONT': 30,
    'V2_SPY_AFTERNOON_FVG': 30,
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': 30,
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': 90,
}
PROTOCOL_BY_STRATEGY = {
    **PROTOCOLS,
    **{sid: f'reviewed_same_contract_{minutes}m_v1' for sid, minutes in TIMED.items()},
}
ACTIVE = {'collecting', 'pending_quote'}


def initialize(*, strategy_id, direction, trigger_bar, meta, selection):
    """Freeze candidate inputs and original selection; never enroll old prices."""
    if selection.get('profile_version') not in PROFILES:
        raise ValueError('Wrong contract-study profile')
    if strategy_id not in PROTOCOL_BY_STRATEGY:
        raise ValueError('No authored exit for this strategy')
    if strategy_id in TIMED and REVIEWED_STRATEGIES[strategy_id].exit_minutes != TIMED[strategy_id]:
        raise ValueError('Reviewed timer changed; new study version required')
    if strategy_id in PROTOCOLS and (strategy_id, meta.get('authored_exit_protocol')) not in SUPPORTED_PROTOCOL_PAIRS:
        raise ValueError('Candidate does not carry the reviewed authored exit')
    if not meta.get('strategy_version') or direction not in {'bullish', 'bearish'}:
        raise ValueError('Missing strategy version or direction')
    contract = selection.get('contract')
    state = dict(profile_version=selection['profile_version'], strategy_id=strategy_id,
                 strategy_version=meta['strategy_version'], protocol=meta.get('authored_exit_protocol') if strategy_id in PROTOCOLS else PROTOCOL_BY_STRATEGY[strategy_id],
                 direction=direction, trigger_bar=et(trigger_bar).isoformat(), meta=deepcopy(meta),
                 status='collecting' if contract else 'no_contract', reason=None,
                 premium_path=dict(partial_bid=None, partial_at=None, quote_count=0, last_bid_at=None))
    if contract:
        ask = contract.get('ask')
        if (selection.get('status') != 'selected' or not isinstance(ask, (int, float))
                or not math.isfinite(ask) or ask <= 0 or not contract.get('symbol')):
            raise ValueError('Invalid selected entry')
        state.update(contract_symbol=contract['symbol'], entry_ask=ask,
                     entry_quote_at=et(contract['entry_quote_at']).isoformat())
        # Validate research feasibility, never substitute a different exit.
        invalid = input_failure(state)
        if invalid:
            state.update(status='unmeasurable', reason=invalid)
    return state


def input_failure(state):
    entry = et(state['trigger_bar'])
    quote = et(state['entry_quote_at'])
    if not 0 <= (quote-entry).total_seconds() <= 60:
        return 'late_entry_quote'
    if state['strategy_id'] in TIMED:
        horizon = quote + timedelta(minutes=TIMED[state['strategy_id']])
        if horizon > entry.replace(hour=16, minute=0, second=0, microsecond=0):
            return 'exit_horizon_outside_session'
    return None


def _event(state, frame, now):
    sid, protocol = state['strategy_id'], state['protocol']
    entry = et(state['trigger_bar'])
    if entry.date() < now.date():
        return entry.replace(hour=15, minute=55), 'missed_session'
    if sid in TIMED:
        cap = et(state['entry_quote_at']) + timedelta(minutes=TIMED[sid])
        return (cap, f'fixed_{TIMED[sid]}m') if now >= cap else None
    args = dict(entry_at=entry, entry_quote_at=state['entry_quote_at'],
                direction=state['direction'], meta=state['meta'], now=now)
    if sid in context_orb_exit.PREMIUM_PROTOCOLS:
        return context_orb_exit.first_exit(frame, strategy_id=sid, **args)
    if sid == squeeze_exit.STRATEGY_ID:
        return squeeze_exit.first_exit(frame, **args)
    return first_exit(protocol, frame, **args)


def advance(state, *, frame=None, now, quote=None):
    """Latch decisions before quote I/O; caller persists the no-quote transition.

    A second call with the response receipt time may price the pending decision.
    Premium targets use sampled bids just like the primary authored collector;
    no unsampled target price or partial profit is manufactured.
    """
    out = deepcopy(state)
    if out['status'] not in ACTIVE:
        return out
    sid = out['strategy_id']
    if out['profile_version'] not in PROFILES or (PROTOCOL_BY_STRATEGY.get(sid) != out['protocol']
            and (sid, out['protocol']) not in SUPPORTED_PROTOCOL_PAIRS):
        raise ValueError('Unknown exit/profile identity')
    now = et(now)
    premium = sid in context_orb_exit.PREMIUM_PROTOCOLS or sid == squeeze_exit.STRATEGY_ID
    # Match the primary matrix's five-minute timer quote window. Context
    # premium/VWAP protocols intentionally use their stricter one-minute cap.
    one_minute = premium or sid in context_vwap_exit.PROTOCOLS
    if out['status'] == 'collecting':
        event = _event(out, frame if frame is not None else pd.DataFrame(), now)
        if event:
            decision, reason = event
            if reason == 'waiting_for_bars':
                return out
            valid = (reason in EXIT_REASONS or reason in {
                'or_midpoint_close', 'hourly_close_below_entry_sma20', 'fixed_30m', 'fixed_90m'})
            out.update(status='pending_quote' if valid else 'unmeasurable',
                       decision_at=et(decision).isoformat(), reason=reason, detected_at=now.isoformat())
    if out['status'] not in ACTIVE:
        return out
    pending = out['status'] == 'pending_quote'
    if pending and now > et(out['decision_at']) + timedelta(minutes=1 if one_minute else 5):
        out['status'] = 'missing_quote'
        return out
    if quote is None or (not premium and not pending):
        return out
    decision = et(out['decision_at']) if pending else max(et(out['entry_quote_at']), now-timedelta(seconds=60))
    priced = executable_bid(quote, contract=out['contract_symbol'], decision_at=decision, received_at=now)
    if not priced or et(priced[1]) <= et(out['entry_quote_at']):
        return out
    bid, stamp = priced
    if premium:
        path = out['premium_path']
        if path['last_bid_at'] and et(stamp) <= et(path['last_bid_at']):
            return out
        path.update(quote_count=path['quote_count']+1, last_bid_at=stamp)
        squeeze = sid == squeeze_exit.STRATEGY_ID
        if not squeeze and not pending and path['partial_bid'] is None and bid+1e-9 >= out['entry_ask']*1.30:
            path.update(partial_bid=bid, partial_at=stamp)
        target = not pending and bid+1e-9 >= out['entry_ask']*(2.5 if squeeze else 2)
        if not target and not pending:
            return out
        if target:
            out.update(decision_at=stamp, detected_at=now.isoformat(),
                       reason='premium_target_150_pct' if squeeze else 'premium_target_100_pct')
    out.update(status='priced', bid=bid, bid_at=stamp, received_at=now.isoformat())
    return out


def normalized_profit(state):
    """Same costs as primary evidence, including the complete NR7/ATR10 plan."""
    profit = net_profit(state)
    if profit is not None and state['strategy_id'] in context_orb_exit.PREMIUM_PROTOCOLS:
        path = state['premium_path']
        if not path['quote_count']:
            return None
        if path['partial_bid'] is not None:
            profit = (profit + net_profit({**state, 'bid': path['partial_bid']}))/2
    return profit
