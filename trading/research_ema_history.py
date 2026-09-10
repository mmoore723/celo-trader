"""Reuse fetched five-minute history for EMA warmup without inventing minute bars."""
import logging
import math
from datetime import time, timedelta

import pandas as pd
from research.engine.data import resample_regular_session
from research.engine.models import Bar

logger=logging.getLogger('celo_trader.research')
NATIVE_POLICY='complete_15m_collected_preferred_native15_v1'


def _native_bars(frame, now):
    """Validate actual provider 15m OHLCV; never expand it into minute bars."""
    cutoff=pd.Timestamp(now)
    if cutoff.tzinfo is not None:
        cutoff=cutoff.tz_convert('America/New_York').tz_localize(None)
    if frame is None or frame.empty:
        return ()
    try:
        data=frame.copy()
        data['time']=pd.to_datetime(data['time'])
        if data['time'].dt.tz is not None:
            data['time']=data['time'].dt.tz_convert('America/New_York').dt.tz_localize(None)
        data=data.loc[~data['time'].duplicated(keep=False)].sort_values('time')
        result=[]
        for row in data.itertuples(index=False):
            stamp=pd.Timestamp(row.time).to_pydatetime()
            o,h,low,c,v=[float(getattr(row,k)) for k in ('open','high','low','close','volume')]
            if (stamp.minute%15 or stamp.second or stamp.microsecond or
                    not time(9,30)<=stamp.time()<time(16) or stamp+timedelta(minutes=15)>cutoff or
                    not all(math.isfinite(x) for x in (o,h,low,c,v)) or min(o,h,low,c)<=0 or v<0 or
                    not low<=min(o,c)<=max(o,c)<=h):
                continue
            result.append(Bar(stamp,o,h,low,c,v))
        return tuple(result)
    except (TypeError,ValueError,KeyError,AttributeError,OverflowError):
        logger.warning('Native EMA candles unusable',exc_info=True)
        return ()


def with_native_ema_history(observed, native, now):
    cutoff=pd.Timestamp(now)
    if cutoff.tzinfo is not None:
        cutoff=cutoff.tz_convert('America/New_York').tz_localize(None)
    latest=(cutoff.floor('15min')-timedelta(minutes=15)).to_pydatetime()
    if not time(9,30)<=latest.time()<time(16) or latest.date()!=cutoff.date():
        return ()
    merged={b.timestamp:b for b in _native_bars(native,now) if b.timestamp<=latest}
    merged.update({b.timestamp:b for b in observed if b.timestamp<=latest})
    if latest not in merged:
        return ()
    return tuple(merged[t] for t in sorted(merged))[-500:]


def native_ema_history(alpaca,ticker,state,now,account,archive=None):
    """One bounded cached read per completed interval; retry delayed bars after 60s."""
    from auth.context import get_current_user_id
    from signals import bars_to_df
    now=pd.Timestamp(now)
    cache=state.setdefault('ema_native_history',{})
    key=(get_current_user_id(),account or '',ticker.upper())
    bucket=now.floor('15min')
    previous=cache.get(key)
    if previous and previous['bucket']==bucket and (previous['complete'] or
            (now-previous['checked']).total_seconds()<60):
        return previous['frame']
    rows,error=alpaca.get_bars(ticker,'15Min',limit=500)
    frame=bars_to_df(rows) if rows and not error else pd.DataFrame()
    if archive is not None:
        today=pd.Timestamp(now).date()
        validated=[dict(time=b.timestamp,open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume)
                   for b in _native_bars(frame,now) if b.timestamp.date()==today]
        if validated:
            archive(pd.DataFrame(validated))
    complete=bool(with_native_ema_history((),frame,now))
    if key not in cache and len(cache)>=128:
        del cache[next(iter(cache))]
    cache[key]=dict(bucket=bucket,checked=now,frame=frame,complete=complete)
    return frame


def with_ema_history(observed, history_5m, now):
    """Prefer complete collected 15m bars; history can only fill earlier gaps.

    A current collected signal candle remains mandatory. History cannot emit
    a stale signal, replace a collected candle, or become a fake 1m tape.
    """
    if not observed or history_5m is None or history_5m.empty:
        return observed
    try:
        cutoff=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='America/New_York')
        if cutoff.tzinfo is not None:
            cutoff=cutoff.tz_convert('America/New_York').tz_localize(None)
        data=history_5m.copy()
        data['time']=pd.to_datetime(data['time'])
        if data['time'].dt.tz is not None:
            data['time']=data['time'].dt.tz_convert('America/New_York').dt.tz_localize(None)
        # Ignore duplicates rather than silently choosing among conflicting bars.
        data=data.loc[~data['time'].duplicated(keep=False)].sort_values('time')
        bars=[]
        for row in data.itertuples(index=False):
            stamp=pd.Timestamp(row.time).to_pydatetime()
            values=[float(getattr(row,k)) for k in ('open','high','low','close','volume')]
            o,h,low,c,v=values
            if (stamp.minute%5 or stamp.second or stamp.microsecond or
                    not time(9,30)<=stamp.time()<time(16) or stamp+timedelta(minutes=5)>cutoff or
                    not all(math.isfinite(x) for x in values) or min(o,h,low,c)<=0 or v<0 or
                    not low<=min(o,c)<=max(o,c)<=h):
                continue
            bars.append(Bar(stamp,o,h,low,c,v))
        historical=resample_regular_session(tuple(bars),source_minutes=5,target_minutes=15)
        latest=observed[-1].timestamp
        merged={b.timestamp:b for b in historical if b.timestamp<latest}
        merged.update({b.timestamp:b for b in observed})
        return tuple(merged[t] for t in sorted(merged))[-500:]
    except (TypeError,ValueError,KeyError,AttributeError,OverflowError):
        logger.warning('EMA history unusable; retaining collected candles',exc_info=True)
        return observed
