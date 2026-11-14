"""Entry-frozen, paper-only pre-profit protection using closed five-minute bars."""
from datetime import timedelta
from decimal import Decimal
import math
from strategy_health.premium_rules import clock, valid_quote

SPEC = {'timeframe_minutes': 5, 'consecutive_candles': 3, 'loss_pct': 10}
REASON = 'adverse_3x5m_10pct_loss'


def validate(policy):
    spec = policy.get('adverse_candle_failsafe')
    if spec is not None and (spec != SPEC or not policy.get('replace_native_exit')
                            or policy.get('gain_pct') != 10 or policy.get('giveback_pct') != 10):
        raise ValueError('Invalid approved adverse-candle fail-safe')
    return spec


def candle_check(frame, entry_at, now, option_type):
    now=clock(now); entry=clock(entry_at)
    end=now.replace(minute=now.minute//5*5,second=0,microsecond=0)
    starts=[end-timedelta(minutes=5*i) for i in (4,3,2,1)]
    if starts[1]<entry:
        return {'status':'waiting_for_three_full_post_entry_candles'}
    if option_type not in ('call','put'):
        return {'status':'option_direction_unavailable'}
    if frame is None or frame.empty or 'time' not in frame or 'close' not in frame:
        return {'status':'completed_5m_candles_unavailable'}
    try:
        rows={}
        for _,row in frame.iterrows():
            at=clock(row['time'])
            if at not in starts:continue
            if at in rows:return {'status':'duplicate_5m_candle'}
            value=float(row['close'])
            if not math.isfinite(value) or value<=0:return {'status':'invalid_5m_close'}
            rows[at]=value
        if any(at not in rows for at in starts):
            return {'status':'latest_completed_5m_candles_missing'}
        closes=[rows[at] for at in starts]
        against=all(b<a if option_type=='call' else b>a for a,b in zip(closes,closes[1:]))
        return {'status':'three_adverse_closes' if against else 'adverse_closes_not_met',
                'adverse':against,'closes':closes,'bar_starts':[at.isoformat() for at in starts],
                'last_bar_closed_at':end.isoformat(),'evaluated_at':now.isoformat()}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {'status':'invalid_5m_candles'}


def apply(state, *, trade, quantity, sold, quote, now, frame):
    out=dict(state)
    if out.get('failsafe_signal'):
        return out,(True,REASON)
    if out.get('activated') or sold>0:
        out['failsafe_status']='disabled_after_profit_activation'
        return out,None
    check=candle_check(frame,trade['entry_time'],now,trade.get('option_type'))
    out['failsafe_check']=check
    q=valid_quote(quote,now,quantity,trade['contract_symbol'])
    if not q:
        out['failsafe_status']='waiting_for_fresh_sized_option_bid'
        return out,None
    entry=Decimal(str(trade['entry_price'])).quantize(Decimal('0.0000000001'))
    loss_met=Decimal(str(q['bid']))<=entry*Decimal('.90')
    out['failsafe_status']='triggered' if check.get('adverse') and loss_met else 'monitoring'
    out['failsafe_check']={**check,'option_bid':q['bid'],'loss_threshold_bid':float(entry*Decimal('.90')),'loss_met':loss_met}
    if check.get('adverse') and loss_met:
        out['failsafe_signal']={**q,'reason':REASON,'candles':check}
        return out,(True,REASON)
    return out,None
