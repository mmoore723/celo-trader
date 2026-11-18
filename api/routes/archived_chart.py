"""Read-only chart history. Never synthesizes missing candles or changes capture."""
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import json
import math
import sqlite3
import zlib
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


@lru_cache(maxsize=6)
def archived_chart(path: str, ticker: str, timeframe: str, period: str, minute_clock: int):
    now = datetime.fromtimestamp(minute_clock * 60, ET)
    days = {'5D': 5, '1M': 30, '3M': 90}[period]
    # 5D means five weekdays; exchange holidays remain explicitly unknown.
    dates = []
    day = now.date()
    while (len(dates) < 5 if period == '5D' else (now.date()-day).days < days):
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    dates.reverse()
    result = dict(bars=[], source='Saved session candles', dates=dates, missing_dates=[],
                  gaps=[], partial_buckets_omitted=0, recovered_minutes=0,
                  note='Missing minutes may mean no trades or missing capture. Closed-market dates are not verified here. No candles are filled in.')
    if not Path(path).exists():
        result['missing_dates'] = dates
        return result
    db = sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    step = {'1Min': 1, '5Min': 5, '15Min': 15, '1Hour': 60}[timeframe]
    try:
        for date in dates:
            indexed = db.execute('SELECT minute,response_id,first_received_at FROM bars WHERE day=? AND ticker=? ORDER BY minute', (date,ticker)).fetchall()
            start = datetime.fromisoformat(date+'T04:00:00').replace(tzinfo=ET)
            end = min(now, start.replace(hour=16))
            indexed = [r for r in indexed if start <= datetime.fromisoformat(r['minute']) < end]
            if not indexed:
                result['missing_dates'].append(date)
                continue
            # A session response normally contains the entire day. Read that first,
            # then older original responses only for minutes missing from it.
            values = {}
            decoded = set()
            def read_response(identity):
                if identity in decoded:
                    return
                decoded.add(identity)
                raw = db.execute('SELECT payload FROM responses WHERE id=?', (identity,)).fetchone()
                if raw is None:
                    return
                payload = json.loads(zlib.decompress(raw[0]))
                rows = (payload.get('series') or {}).get('data') or []
                if isinstance(rows,dict): rows=[rows]
                for row in rows:
                    stamp = datetime.fromisoformat(row['time'])
                    stamp = stamp.replace(tzinfo=ET) if stamp.tzinfo is None else stamp.astimezone(ET)
                    if not start <= stamp < end or stamp+timedelta(minutes=1)>now:
                        continue
                    nums = {k:float(row[k]) for k in ('open','high','low','close','volume')}
                    if not all(math.isfinite(v) for v in nums.values()): continue
                    values.setdefault(stamp.isoformat(),dict(time=stamp.replace(tzinfo=None).isoformat(),**nums))
            read_response(indexed[-1]['response_id'])
            for r in indexed:
                if r['minute'] not in values: read_response(r['response_id'])
            known = {r['minute']:r for r in indexed}
            values = {t:b for t,b in values.items() if t in known}
            missing=[]
            for n in range(max(0,int((end-start).total_seconds()//60))):
                stamp=start+timedelta(minutes=n)
                if stamp.isoformat() not in values: missing.append(stamp)
            for stamp in missing:
                if result['gaps'] and result['gaps'][-1]['end']==stamp.isoformat():
                    result['gaps'][-1]['end']=(stamp+timedelta(minutes=1)).isoformat()
                    result['gaps'][-1]['minutes']+=1
                else: result['gaps'].append(dict(start=stamp.isoformat(),end=(stamp+timedelta(minutes=1)).isoformat(),minutes=1))
            buckets={}; total_volume=0.; total_value=0.
            for stamp,b in sorted(values.items()):
                r=known[stamp]
                if (datetime.fromisoformat(r['first_received_at'])-datetime.fromisoformat(stamp)-timedelta(minutes=1)).total_seconds()>300:
                    result['recovered_minutes']+=1
                total_volume+=b['volume']; total_value+=(b['high']+b['low']+b['close'])/3*b['volume']
                b['vwap']=total_value/total_volume if total_volume else None
                d=datetime.fromisoformat(b['time']); key=d.replace(minute=(d.minute//step)*step)
                buckets.setdefault(key,[]).append(b)
            for key,group in sorted(buckets.items()):
                if len(group)!=step:
                    result['partial_buckets_omitted']+=1
                    continue
                result['bars'].append(dict(time=key.isoformat(),open=group[0]['open'],high=max(b['high'] for b in group),low=min(b['low'] for b in group),close=group[-1]['close'],volume=sum(b['volume'] for b in group),vwap=group[-1]['vwap']))
    finally:
        db.close()
    return result
