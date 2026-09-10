"""Frozen context-ORB midpoint decisions; premium exits use real quotes."""
from datetime import timedelta
from functools import lru_cache
import hashlib
import inspect
import math

from strategies import context_strategy_observers as source
from strategy_health.impulse_exit import et

STRATEGY_ID = source.ORB_NR7_INSIDE
PROTOCOL = 'context_orb_nr7_premium_partials_midpoint_1555_v1'
PREMIUM_PROTOCOLS = {STRATEGY_ID: PROTOCOL}
ATR10_STRATEGY_ID = source.ORB_ATR10_LONG
ATR10_PROTOCOL = 'context_orb_atr10_premium_partials_midpoint_1555_v1'
PREMIUM_PROTOCOLS[ATR10_STRATEGY_ID] = ATR10_PROTOCOL


@lru_cache(maxsize=1)
def engine_hash():
    return hashlib.sha256(inspect.getsource(source).encode()).hexdigest()


def metadata(strategy_id):
    if strategy_id not in PREMIUM_PROTOCOLS:
        return {}
    state = {'engine_hash':engine_hash(), 'policy':'midpoint_close_1555_30_100_v1'}
    # Preserve existing NR7 records; ATR10 proof cannot be borrowed from NR7.
    if strategy_id == ATR10_STRATEGY_ID:
        state['strategy_id'] = strategy_id
    return {'authored_exit_protocol':PREMIUM_PROTOCOLS[strategy_id], 'authored_exit_state':state}


def first_exit(frame, *, entry_at, entry_quote_at, direction, meta, now, strategy_id=STRATEGY_ID):
    entry, now = et(entry_at), et(now)
    expected = metadata(strategy_id)
    if not expected or meta.get('authored_exit_state') != expected['authored_exit_state']:
        return entry, 'missing_exit_state'
    if strategy_id == ATR10_STRATEGY_ID and direction != 'bullish':
        return entry, 'invalid_direction'
    cap = entry.replace(hour=15,minute=55)
    if entry.second or entry.microsecond or not entry.replace(hour=9,minute=30)<=entry<cap:
        return entry,'invalid_entry'
    if not entry<=et(entry_quote_at)<entry+timedelta(minutes=1):
        return entry,'late_entry_quote'
    try:
        midpoint=float(meta['or_midpoint'])
        if not math.isfinite(midpoint) or midpoint<=0 or direction not in {'bullish','bearish'}:
            raise ValueError('invalid midpoint')
    except (KeyError,TypeError,ValueError):
        return entry,'invalid_levels'
    rows={}
    for row in frame.to_dict('records'):
        stamp=et(row['time'])
        if stamp in rows:
            return entry,'duplicate_bars'
        rows[stamp]=row
    start=entry+timedelta(minutes=1)
    while start+timedelta(minutes=1)<=min(now,cap):
        decision=start+timedelta(minutes=1)
        row=rows.get(start)
        if row is None:
            return decision,'missing_bars' if now>decision+timedelta(minutes=5) else 'waiting_for_bars'
        try:
            o,h,low,c=[float(row[k]) for k in ('open','high','low','close')]
            if not all(math.isfinite(v) and v>0 for v in (o,h,low,c)) or not low<=min(o,c)<=max(o,c)<=h:
                raise ValueError('invalid OHLC')
        except (KeyError,TypeError,ValueError):
            return decision,'invalid_bars'
        if c<=midpoint if direction=='bullish' else c>=midpoint:
            return decision,'or_midpoint_close'
        if decision==cap:
            return decision,'eod_1555_cap'
        start=decision
    return None
