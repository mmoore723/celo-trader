"""Explicit, scoped execution controls. No override means unchanged engine behavior."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import math

_exit = ContextVar('frozen_execution_controls', default={})

def defaults(sid, ticker):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from config.research_order_specs import SPECS
    from trading.entry.contract import reviewed_contract_profile
    rule=REVIEWED_STRATEGIES[sid];spec=SPECS.get(sid);source=spec.source if spec else sid
    profile=reviewed_contract_profile(sid,ticker)
    contract={k:getattr(profile,k) for k in ('minimum_dte','maximum_dte','minimum_premium','maximum_premium','maximum_spread_pct','primary_policy')}
    from config import MIN_OPEN_INTEREST, MAX_BID_ASK_SPREAD
    legacy=not (sid=='V2_TREND_CONT' or sid in SPECS)
    contract.update(minimum_open_interest=MIN_OPEN_INTEREST if legacy else 0,maximum_spread_dollars=MAX_BID_ASK_SPREAD if legacy else 0.)
    out={}
    hold=rule.exit_minutes
    if spec and spec.adapter in ('native_trend','native_fvg','retouch','two_leg'):hold=spec.reference_minutes
    if sid in ('RESEARCH_FAILED_RANGE_V2','RESEARCH_QQQ_TREND_V2'):hold=30
    if hold is not None:out['hold_minutes']=hold
    structural={'V2_TREND_CONT','V2_VWAP_PULLBACK','V2_AFTERNOON_REVERSAL','V2_FAIR_VALUE_GAP','V2_MIDDAY_BREAKDOWN','V2_ORB_CONFIRMED_BREAKOUT','V2_TURTLE_SOUP_RTH','V2_VWAP_REVERSION_RTH','V2_EMA_PULLBACK_RTH','V2_SPY_ORB_RSI_MACD_SHORT','V2_IMPULSE_ANCHORED_VWAP_PULLBACK','V2_AFTERNOON_COMPRESSION_BREAKOUT','V2_RANGE_SWEEP_RECLAIM'}
    if source in structural:
        out.update(max_hold_bars=24 if source=='V2_IMPULSE_ANCHORED_VWAP_PULLBACK' else 390 if source in ('V2_AFTERNOON_COMPRESSION_BREAKOUT','V2_RANGE_SWEEP_RECLAIM') else 75)
    if sid=='V2_TSLA_TWO_LEG_TREND_PULLBACK':out.update(legacy_arm_dollars=65.,legacy_giveback_pct=35.)
    if source in ('CTX_ORB_NR7_OR_INSIDE','CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG'):
        out.update(partial_gain_pct=30.,final_gain_pct=100.)
    if source=='CTX_1H_SQUEEZE_MACD_LONG':out['final_gain_pct']=150.
    if sid=='CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG':out['missing_structure_hold_minutes']=90
    if rule.observation_only:out={}
    return {'contract':contract,'native_exit':out}


def validate(sid,ticker,values):
    expected=defaults(sid,ticker)
    if not isinstance(values,dict) or set(values)-set(expected):raise ValueError('Unknown execution section')
    parsed={}
    for section,fields in values.items():
        if section=='native_exit':expected[section].setdefault('hold_minutes',30)
        if not isinstance(fields,dict) or set(fields)-set(expected[section]):raise ValueError('Unknown execution setting')
        merged={**expected[section],**fields}
        for key,value in merged.items():
            base=expected[section][key]
            if isinstance(base,bool):
                if type(value) is not bool:raise ValueError(key+': choose on or off')
            elif isinstance(base,str):
                from config.research_pair_policy import CONTRACTS
                if value not in {*CONTRACTS,base,'reviewed_target_150_250'}:raise ValueError('Unsupported contract ranking')
            elif isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(key+': enter a finite number')
            elif isinstance(base,int) and (int(value)!=value or not 0<=value<=2000):raise ValueError(key+': enter a whole number from 0 to 2000')
            elif not 0<=value<=10000:raise ValueError(key+': value outside supported range')
        if section=='contract':
            if not 0<=merged['minimum_dte']<=merged['maximum_dte']<=730:raise ValueError('Expiration days must be between 0 and 730, minimum first')
            if not 0<merged['minimum_premium']<=merged['maximum_premium']:raise ValueError('Premium minimum must be positive and at most the maximum')
            if not 0<merged['maximum_spread_pct']<=1:raise ValueError('Spread must be above 0 and at most 1 (100%)')
        else:
            for key,value in merged.items():
                if not isinstance(value,bool) and value<=0:raise ValueError(key+': must be positive')
            if merged.get('legacy_giveback_pct',1)>=100:raise ValueError('Giveback must be below 100%')
            if merged.get('partial_gain_pct',0)>=merged.get('final_gain_pct',float('inf')):raise ValueError('Partial gain must be below final gain')
        parsed[section]=merged if section=='contract' else dict(fields)
    return parsed


def saved(settings,sid,ticker):
    from config.engine_parameters import KEY,scope_key
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule=REVIEWED_STRATEGIES.get(sid)
    if not rule:return {}
    value=(settings.get(KEY) or {}).get(scope_key(settings,sid,ticker,rule.version),{}).get('execution')
    return validate(sid,ticker,value) if value else {}


def freeze(settings,sid,ticker):
    values=saved(settings,sid,ticker)
    if not values:return {}
    from config.engine_parameters import revision
    policy={'strategy_id':sid,'ticker':ticker,'values':values}
    return {'execution_controls':{**policy,'digest':revision(policy)}}


@contextmanager
def from_trade(trade):
    raw=trade.get('strategy_context_json') or {}
    context=json.loads(raw) if isinstance(raw,str) else raw
    policy=context.get('execution_controls')
    values={}
    if policy:
        from config.engine_parameters import revision
        plain={k:v for k,v in policy.items() if k!='digest'}
        if (policy.get('digest')!=revision(plain) or policy.get('strategy_id')!=trade.get('strategy_id') or policy.get('ticker')!=trade.get('ticker')):raise ValueError('Invalid frozen execution controls')
        values=validate(policy['strategy_id'],policy['ticker'],policy['values']).get('native_exit',{})
    token=_exit.set(values)
    try:yield
    finally:_exit.reset(token)


def trade_controls(fn):
    signature=inspect.signature(fn)
    @wraps(fn)
    def wrapped(*args,**kwargs):
        trade=signature.bind(*args,**kwargs).arguments['trade']
        with from_trade(trade):return fn(*args,**kwargs)
    return wrapped


def exit_value(name,default):return _exit.get().get(name,default)


def describe_execution(settings,sid,ticker,policy=None):
    from config.research_pair_policy import selected
    from config.strategy_catalog import REVIEWED_STRATEGIES
    baseline=defaults(sid,ticker)
    chosen=selected(settings,sid,ticker,REVIEWED_STRATEGIES[sid].version)
    overrides=saved(settings,sid,ticker)
    current={k:{**v,**overrides.get(k,{})} for k,v in baseline.items()}
    if chosen and chosen.get('contract_policy') and not overrides.get('contract'):current['contract']['primary_policy']=chosen['contract_policy']
    if chosen and chosen.get('exit_minutes') is not None and not overrides.get('native_exit'):current['native_exit']['hold_minutes']=chosen['exit_minutes']
    if policy and policy.get('replace_native_exit'):current['native_exit']={}
    return current
