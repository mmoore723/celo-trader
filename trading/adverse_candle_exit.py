"""Entry-frozen, paper-only pre-profit protection using completed configured-timeframe bars."""
from datetime import timedelta
from decimal import Decimal
import math
import re

def is_failsafe_reason(reason):
    return reason == 'chart_invalidation_1x5m' or bool(re.fullmatch(r"adverse_\d+x\d+m_[0-9.]+pct_loss", str(reason or "")))

from strategy_health.premium_rules import clock, quote_validation

TIMEFRAMES = (1,2,3,4,5,10,15,20,30,60)

SPEC = {'timeframe_minutes': 5, 'consecutive_candles': 3, 'loss_pct': 10}
REASON = 'adverse_3x5m_10pct_loss'


def validate(policy):
    spec = policy.get('adverse_candle_failsafe')
    if policy.get('configuration_editor') == 1:
        if spec is not None:
            if (not isinstance(spec,dict) or set(spec)!=set(SPEC) or type(spec.get('timeframe_minutes')) is not int or spec.get('timeframe_minutes') not in TIMEFRAMES
                    or type(spec.get('consecutive_candles')) is not int or not 1<=spec['consecutive_candles']<=12
                    or isinstance(spec.get('loss_pct'),bool) or not isinstance(spec.get('loss_pct'),(int,float))
                    or not math.isfinite(spec['loss_pct']) or not 0<spec['loss_pct']<100):
                raise ValueError('Invalid candle fail-safe configuration')
    elif spec is not None and (spec != SPEC or not policy.get('replace_native_exit')
                            or policy.get('gain_pct') != 10 or policy.get('giveback_pct') != 10):
        raise ValueError('Invalid approved adverse-candle fail-safe')
    return spec


def candle_check(frame, entry_at, now, option_type, count=3, timeframe_minutes=5):
    now=clock(now); entry=clock(entry_at)
    end=now.replace(minute=now.minute//timeframe_minutes*timeframe_minutes,second=0,microsecond=0)
    starts=[end-timedelta(minutes=timeframe_minutes*i) for i in range(count+1,0,-1)]
    if starts[1]<entry:
        return {'status':'waiting_for_three_full_post_entry_candles' if count==3 else f'waiting_for_{count}_full_post_entry_candles'}
    if option_type not in ('call','put'):
        return {'status':'option_direction_unavailable'}
    if frame is None or frame.empty or 'time' not in frame or 'close' not in frame:
        return {'status':f'completed_{timeframe_minutes}m_candles_unavailable'}
    try:
        rows={}
        for _,row in frame.iterrows():
            at=clock(row['time'])
            if at not in starts:continue
            if at in rows:return {'status':f'duplicate_{timeframe_minutes}m_candle'}
            value=float(row['close'])
            if not math.isfinite(value) or value<=0:return {'status':f'invalid_{timeframe_minutes}m_close'}
            rows[at]=value
        if any(at not in rows for at in starts):
            return {'status':f'latest_completed_{timeframe_minutes}m_candles_missing'}
        closes=[rows[at] for at in starts]
        against=all(b<a if option_type=='call' else b>a for a,b in zip(closes,closes[1:]))
        return {'consecutive_candles':count,'status':('three_adverse_closes' if count==3 else f'{count}_adverse_closes') if against else 'adverse_closes_not_met',
                'adverse':against,'closes':closes,'bar_starts':[at.isoformat() for at in starts],
                'last_bar_closed_at':end.isoformat(),'evaluated_at':now.isoformat()}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {'status':f'invalid_{timeframe_minutes}m_candles'}


def apply(state, *, trade, quantity, sold, quote, now, frame, spec=None):
    spec=spec or SPEC
    reason=REASON if spec==SPEC else f"adverse_{spec['consecutive_candles']}x{spec['timeframe_minutes']}m_{spec['loss_pct']:g}pct_loss"
    out=dict(state)
    if out.get('failsafe_signal'):
        return out,(True,reason)
    if out.get('activated') or sold>0:
        out['failsafe_status']='disabled_after_profit_activation'
        return out,None
    check=candle_check(frame,trade['entry_time'],now,trade.get('option_type'),spec['consecutive_candles'],spec['timeframe_minutes'])
    out['failsafe_check']=check
    q, validation=quote_validation(quote,now,quantity,trade['contract_symbol'])
    out['failsafe_quote_check']=validation
    if not q:
        out['failsafe_status']='waiting_for_fresh_sized_option_bid'
        return out,None
    entry=Decimal(str(trade['entry_price'])).quantize(Decimal('0.0000000001'))
    loss_met=Decimal(str(q['bid']))<=entry*(1-Decimal(str(spec['loss_pct']))/100)
    out['failsafe_status']='triggered' if check.get('adverse') and loss_met else 'monitoring'
    out['failsafe_check']={**check,'option_bid':q['bid'],'loss_threshold_bid':float(entry*(1-Decimal(str(spec['loss_pct']))/100)),'loss_met':loss_met}
    if check.get('adverse') and loss_met:
        out['failsafe_signal']={**q,'reason':reason,'candles':check}
        return out,(True,reason)
    return out,None


def configured_frame(alpaca, ticker, policy, now, cache, default_five_minute):
    """Custom intervals use complete one-minute source bars, never a feed fallback interval."""
    spec=validate(policy or {})
    if not spec or spec['timeframe_minutes']==5:return default_five_minute
    import pandas as pd
    minutes=spec['timeframe_minutes']; current=clock(now)
    key=current.replace(second=0,microsecond=0).isoformat()
    if cache.get('failsafe_minutes_key')!=key:
        try:
            bars,error,_=alpaca.get_session_bars(ticker,'1Min')
            if error or not bars:return None
            from signals import bars_to_df
            source=bars_to_df(bars)
            cache['failsafe_minutes']=source
            cache['failsafe_minutes_key']=key
        except Exception:
            return None
    source=cache.get('failsafe_minutes')
    if source is None or source.empty:return None
    groups={}
    for _,row in source.iterrows():
        at=clock(row['time'])
        if at.second or at.microsecond:continue
        start=at.replace(minute=at.minute//minutes*minutes)
        if start+timedelta(minutes=minutes)>current:continue
        groups.setdefault(start,[]).append((at,row['close']))
    completed=[]
    for start,rows in groups.items():
        expected={start+timedelta(minutes=i) for i in range(minutes)}
        if len(rows)!=minutes or {at for at,_ in rows}!=expected:continue
        if any(not math.isfinite(float(v)) or float(v)<=0 for _,v in rows):continue
        completed.append({'time':start,'close':sorted(rows,key=lambda r:r[0])[-1][1]})
    return pd.DataFrame(completed,columns=['time','close'])
