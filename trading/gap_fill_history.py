from datetime import time, timedelta
import math

import pandas as pd

from research.engine.models import Bar


def completed_history(frame, now):
    if frame is None or frame.empty:
        return ()
    cutoff = pd.Timestamp(now)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert('America/New_York').tz_localize(None)
    data = frame.copy()
    data['time'] = pd.to_datetime(data['time'])
    if data['time'].dt.tz is not None:
        data['time'] = data['time'].dt.tz_convert('America/New_York').dt.tz_localize(None)
    data = data.loc[~data['time'].duplicated(keep=False)].sort_values('time')
    result = []
    for row in data.itertuples(index=False):
        stamp = pd.Timestamp(row.time).to_pydatetime()
        values = [float(getattr(row, key)) for key in ('open', 'high', 'low', 'close', 'volume')]
        o, h, low, c, v = values
        if (stamp.minute % 5 or stamp.second or stamp.microsecond
                or not time(9, 30) <= stamp.time() <= time(15, 55)
                or stamp + timedelta(minutes=5) > cutoff
                or not all(math.isfinite(value) for value in values)
                or min(o, h, low, c) <= 0 or v < 0 or not low <= min(o, c) <= max(o, c) <= h):
            continue
        result.append(Bar(stamp, o, h, low, c, v))
    return tuple(result)


def with_history(observed, native, now):
    if not observed:
        return ()
    latest = observed[-1].timestamp
    merged = {bar.timestamp: bar for bar in completed_history(native, now) if bar.timestamp < latest}
    merged.update({bar.timestamp: bar for bar in observed})
    return tuple(merged[stamp] for stamp in sorted(merged))[-500:]


def valid_session_context(bars):
    if not bars:
        return False
    day = bars[-1].timestamp.date()
    previous = [bar for bar in bars if bar.timestamp.date() < day]
    today = [bar for bar in bars if bar.timestamp.date() == day]
    if not previous or today[0].timestamp.time() != time(9, 30):
        return False
    if previous[-1].timestamp.time() != time(15, 55):
        return False
    between = previous[-1].timestamp.date() + timedelta(days=1)
    while between < day:
        if between.weekday() < 5:
            return False
        between += timedelta(days=1)
    return True
