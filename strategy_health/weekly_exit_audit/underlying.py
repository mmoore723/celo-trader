"""Read existing account-scoped scanner candles without mutating history."""
from datetime import timedelta
import math

from database.helpers import _to_et_datetime


def load_path(conn, trade, horizon):
    account=trade.get('broker_account_id')
    info={'source':'scanner_candle_observations','status':'unavailable',
          'point_in_time_vintage_verified':False}
    if not account:
        info['status']='unknown_account'
        return None,info
    try:
        start=_to_et_datetime(trade.get('entry_fill_time') or trade['entry_time']).replace(second=0,microsecond=0)
        end=_to_et_datetime(horizon)
        if end<=start or end-start>timedelta(days=7):
            raise ValueError('invalid_horizon')
    except (ValueError,TypeError,AttributeError):
        info['status']='invalid_horizon'
        return None,info
    info.update(start=start.isoformat(),end=end.isoformat())
    rows=conn.execute('''SELECT bar_time,open,high,low,close,volume,source,recorded_at
        FROM scanner_candle_observations WHERE broker_account_id=? AND ticker=?
        AND timeframe='1Min' AND bar_time>=? AND bar_time<? ORDER BY bar_time''',
        (account,trade['ticker'],start.date().isoformat(),(end.date()+timedelta(days=1)).isoformat())).fetchall()
    bars={}; sources=set()
    for row in rows:
        try:
            at=_to_et_datetime(row['bar_time'])
            if not start<=at or at+timedelta(minutes=1)>end:
                continue
            if at.second or at.microsecond or at in bars:
                raise ValueError('invalid_bar_time')
            values={k:float(row[k]) for k in ('open','high','low','close','volume')}
            if (not all(math.isfinite(v) for v in values.values()) or values['volume']<0
                    or not 0<values['low']<=min(values['open'],values['close'])
                    <=max(values['open'],values['close'])<=values['high']):
                raise ValueError('invalid_bar')
            sources.add(row['source'])
            bars[at]={'time':at.isoformat(),**values,'source':row['source'],'recorded_at':row['recorded_at']}
        except (TypeError,ValueError,AttributeError):
            info['status']='invalid_or_duplicate_candles'
            return None,info
    expected=int((end-start).total_seconds()//60)
    missing=[(start+timedelta(minutes=i)).isoformat() for i in range(expected)
             if start+timedelta(minutes=i) not in bars]
    info.update(expected_bars=expected,captured_bars=len(bars),missing_bars=len(missing),
                first_missing=missing[:5],sources=sorted(str(s) for s in sources))
    if missing or not bars or len(sources)!=1:
        info['status']='missing_candles' if missing or not bars else 'mixed_sources'
        return None,info
    info['status']='complete_recorded_ohlc_not_tick_path'
    return [bars[k] for k in sorted(bars)],info
