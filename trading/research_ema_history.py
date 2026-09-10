"""Reuse fetched five-minute history for EMA warmup without inventing minute bars."""
import logging
import math
from datetime import time, timedelta

import pandas as pd
from research.engine.data import resample_regular_session
from research.engine.models import Bar

logger=logging.getLogger('celo_trader.research')


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
