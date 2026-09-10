"""Frozen hourly Squeeze exit proof; actual premiums are priced separately."""
from datetime import timedelta
import math

from strategies.context_strategy_observers import SQUEEZE_MACD_LONG
from strategy_health.context_orb_exit import engine_hash
from strategy_health.impulse_exit import et

STRATEGY_ID = SQUEEZE_MACD_LONG
PROTOCOL = 'squeeze_frozen_sma20_hourly_premium150_1555_v1'


def metadata(strategy_id):
    if strategy_id != STRATEGY_ID:
        return {}
    return {'authored_exit_protocol':PROTOCOL,'authored_exit_state':{
        'engine_hash':engine_hash(),'strategy_id':strategy_id,
        'policy':'frozen_sma20_hourly_premium150_1555_v1'}}


def first_exit(frame, *, entry_at, entry_quote_at, direction, meta, now):
    entry,now=et(entry_at),et(now)
    if meta.get('authored_exit_state') != metadata(STRATEGY_ID)['authored_exit_state']:
        return entry,'missing_exit_state'
    cap=entry.replace(hour=15,minute=55)
    if entry.minute!=30 or entry.second or entry.microsecond or not entry.replace(hour=10,minute=30)<=entry<cap:
        return entry,'invalid_entry'
    if direction!='bullish':
        return entry,'invalid_direction'
    if not entry<=et(entry_quote_at)<entry+timedelta(minutes=1):
        return entry,'late_entry_quote'
    try:
        baseline=float(meta['sma20'])
        if not math.isfinite(baseline) or baseline<=0:
            raise ValueError('invalid SMA')
    except (KeyError,TypeError,ValueError):
        return entry,'invalid_levels'
    rows={}
    for row in frame.to_dict('records'):
        stamp=et(row['time'])
        if not entry<=stamp<min(now,cap):
            continue
        if stamp in rows:
            return entry,'duplicate_bars'
        rows[stamp]=row
    start=entry
    while start+timedelta(hours=1)<=min(now,cap):
        decision=start+timedelta(hours=1)
        bucket=[rows.get(start+timedelta(minutes=i)) for i in range(60)]
        if any(row is None for row in bucket):
            return decision,'missing_bars' if now>decision+timedelta(minutes=5) else 'waiting_for_bars'
        for row in bucket:
            try:
                o,h,low,c=[float(row[k]) for k in ('open','high','low','close')]
                if not all(math.isfinite(v) and v>0 for v in (o,h,low,c)) or not low<=min(o,c)<=max(o,c)<=h:
                    raise ValueError('invalid OHLC')
            except (KeyError,TypeError,ValueError):
                return decision,'invalid_bars'
        if float(bucket[-1]['close'])<baseline:
            return decision,'hourly_close_below_entry_sma20'
        start=decision
    # The frozen replay explicitly capped at 15:55; the last partial hour
    # is not a completed hourly candle and cannot trigger the SMA rule.
    return (cap,'eod_1555_cap') if now>=cap else None
