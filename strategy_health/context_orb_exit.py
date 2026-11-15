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
    if not expected or not compatible_state(meta.get('authored_exit_state'),expected['authored_exit_state']):
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
    from config.execution_parameters import exit_value
    interval=exit_value('structural_timeframe_minutes',1)
    opening=entry.replace(hour=9,minute=30,second=0,microsecond=0)
    start=opening+timedelta(minutes=(int((entry-opening).total_seconds()/60)//interval+1)*interval)
    while start+timedelta(minutes=interval)<=min(now,cap):
        decision=start+timedelta(minutes=interval)
        bucket=[rows.get(start+timedelta(minutes=i)) for i in range(interval)]
        row=bucket[-1] if all(b is not None for b in bucket) else None
        if row is None:
            return decision,'missing_bars' if now>decision+timedelta(minutes=5) else 'waiting_for_bars'
        try:
            for item in bucket:
                o,h,low,c=[float(item[k]) for k in ('open','high','low','close')]
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


# Entry inputs changed in the settings release; authored exit algorithms did not.
PREVIOUS_ENTRY_HASH = '9b4c36afa8f65ea5841f520fd9a18238802b77681f80ccc583ed5439f98327ff'
def compatible_state(actual, expected):
    if actual==expected:return True
    if not isinstance(actual,dict) or actual.get('engine_hash') not in (PREVIOUS_ENTRY_HASH,'6c30c61af5541dd908b31be05514db821fdc79d63a80d1a3e13f7624830fb500'):return False
    revised={**actual,'engine_hash':expected.get('engine_hash')}
    if revised.get('execution_exit_hash')=='153aa9353db78113c7b8f9a186ae0e2998782d353121234e59fa9f29c0518221':
        revised['execution_exit_hash']=expected.get('execution_exit_hash')
    return revised==expected
