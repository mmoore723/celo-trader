"""Measured context VWAP exits; never order routing or synthetic option prices."""
from datetime import timedelta
from functools import lru_cache
import hashlib
import inspect
import math

from strategies.context_strategy_observers import VWAP_KER10_LONG, VWAP_DISPLACEMENT_LONG
from trading import vwap_displacement_exit as displacement_source
from strategy_health.context_orb_exit import engine_hash
from strategy_health.impulse_exit import et

STRATEGY_ID = VWAP_KER10_LONG
PROTOCOL = 'context_vwap_ker_prior_high_5m_vwap_1555_v1'
DISPLACEMENT_STRATEGY_ID = VWAP_DISPLACEMENT_LONG
DISPLACEMENT_PROTOCOL = 'context_vwap_displacement_prior_high_5m_vwap_1555_v1'
PROTOCOLS = {STRATEGY_ID:PROTOCOL, DISPLACEMENT_STRATEGY_ID:DISPLACEMENT_PROTOCOL}


@lru_cache(maxsize=1)
def displacement_exit_hash():
    return hashlib.sha256(inspect.getsource(displacement_source).encode()).hexdigest()


def metadata(strategy_id):
    if strategy_id not in PROTOCOLS:
        return {}
    state = {
        'engine_hash':engine_hash(), 'strategy_id':strategy_id,
        'policy':'prior_high_1m_session_vwap_5m_1555_v1'}
    if strategy_id == DISPLACEMENT_STRATEGY_ID:
        state['execution_exit_hash'] = displacement_exit_hash()
    return {'authored_exit_protocol':PROTOCOLS[strategy_id], 'authored_exit_state':state}


def first_exit(frame, *, entry_at, entry_quote_at, direction, meta, now, strategy_id=STRATEGY_ID):
    entry, now = et(entry_at), et(now)
    expected = metadata(strategy_id)
    if not expected or meta.get('authored_exit_state') != expected['authored_exit_state']:
        return entry,'missing_exit_state'
    opening, cap = entry.replace(hour=9,minute=30), entry.replace(hour=15,minute=55)
    if entry.minute%5 or entry.second or entry.microsecond or not opening<=entry<cap:
        return entry,'invalid_entry'
    if direction != 'bullish':
        return entry,'invalid_direction'
    # One-minute high cannot safely describe a purchase later than that minute.
    if not entry<=et(entry_quote_at)<entry+timedelta(minutes=1):
        return entry,'late_entry_quote'
    try:
        target=float(meta['previous_high'])
        if not math.isfinite(target) or target<=0:
            raise ValueError('invalid prior high')
    except (KeyError,TypeError,ValueError):
        return entry,'invalid_levels'
    rows={}
    for row in frame.to_dict('records'):
        stamp=et(row['time'])
        if not opening<=stamp<min(now,cap):
            continue
        if stamp in rows:
            return entry,'duplicate_bars'
        rows[stamp]=row
    start=opening
    bucket=[]
    price_volume=volume=0.0
    while start+timedelta(minutes=1)<=min(now,cap):
        decision=start+timedelta(minutes=1)
        row=rows.get(start)
        if row is None:
            return (decision,'missing_bars') if now>decision+timedelta(minutes=5) else None
        try:
            o,h,low,c,v=[float(row[k]) for k in ('open','high','low','close','volume')]
            if (not all(math.isfinite(x) and x>0 for x in (o,h,low,c))
                    or not math.isfinite(v) or v<0 or not low<=min(o,c)<=max(o,c)<=h):
                raise ValueError('invalid OHLCV')
        except (KeyError,TypeError,ValueError):
            return decision,'invalid_bars'
        bucket.append((h,low,c,v))
        reached=start>entry and h>=target
        if decision.minute%5==0:
            weight=max(sum(item[3] for item in bucket),1.0)
            typical=(max(item[0] for item in bucket)+min(item[1] for item in bucket)+c)/3
            price_volume+=typical*weight
            volume+=weight
            bucket=[]
            # Equal-time target/stop uses the saved replay's target-first tie.
            if decision>entry and not reached and c<price_volume/volume:
                return decision,'five_minute_close_below_vwap'
        if reached:
            return decision,'prior_high_target'
        if decision==cap:
            return decision,'eod_1555_cap'
        start=decision
    return None
