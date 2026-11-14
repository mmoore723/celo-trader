"""Account/mode/pair-scoped engine inputs. Empty overrides preserve engine defaults."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import time, date, datetime, timezone
from hashlib import sha256
import importlib
import json
import math

KEY = 'strategy_engine_parameters'
_current = ContextVar('engine_parameters', default=None)
NATIVE = {
 'V2_ORB_PULLBACK': ('trading.orb_retouch_execution', ['RETOUCH_TOLERANCE_PCT','ENTRY_DEADLINE']),
 'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('trading.two_leg_trend_pullback_execution', ['REFERENCE_TIME','ENTRY_START','ENTRY_END','FAST_EMA','SLOW_EMA','ATR_BARS','IMPULSE_ATR','PULLBACK_MIN_ATR','PULLBACK_MAX_ATR','PULLBACK_LIMIT_BARS','REWARD_RISK']),
 'V2_SPY_AFTERNOON_FVG': ('strategies.spy_afternoon_fvg_v2', ['_FAST_EMA','_SLOW_EMA','_ATR_BARS','_SCAN_BARS','_MIN_GAP_ATR','_START','_END']),
 'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('strategies.spy_failed_range_recovery_v2', ['BREAKOUT_DEADLINE','FAILURE_DEADLINE','MINIMUM_EXCURSION_RANGE','MINIMUM_VWAP_ROOM_RANGE','STOP_BUFFER_RANGE']),
}

def encode(value):
    return value.isoformat() if isinstance(value,(time,date)) else value

def revision(value):
    return sha256(json.dumps(value,sort_keys=True,default=encode).encode()).hexdigest()

def scope_key(settings,sid,ticker,version):
    return json.dumps([settings.get('active_broker_account_id') or '', 'paper' if settings.get('paper_trading',True) else 'live',sid,ticker.upper(),version],separators=(',',':'))

def definition(sid):
    from config.research_order_specs import SPECS
    from config.strategy_catalog import REVIEWED_STRATEGIES
    if sid not in REVIEWED_STRATEGIES: raise ValueError('Unknown strategy')
    spec=SPECS.get(sid)
    native=sid
    if spec and spec.adapter=='native_trend': native='V2_SPY_TREND_CONT'
    if sid=='RESEARCH_FAILED_RANGE_V2': native='V2_FAILED_OR_BREAK_VWAP_REVERSION'
    if spec and spec.adapter=='two_leg': native='V2_TSLA_TWO_LEG_TREND_PULLBACK'
    if spec and spec.adapter=='retouch': native='V2_ORB_PULLBACK'
    if spec and spec.adapter=='native_fvg': native='V2_SPY_AFTERNOON_FVG'
    if sid=='RESEARCH_QQQ_TREND_V2': native='V2_SPY_TREND_CONT'
    if native in NATIVE:
        module,names=NATIVE[native];mod=importlib.import_module(module)
        return {name.lower().lstrip('_'):getattr(mod,name) for name in names}
    source=spec.source if spec else sid
    if source in CONTEXT_DEFAULTS:return dict(CONTEXT_DEFAULTS[source])
    if native=='V2_TREND_CONT':
        from research.engine.strategies.trend_continuation import TrendContinuationConfig
        obj=TrendContinuationConfig()
    elif native=='V2_SPY_TREND_CONT':
        from strategies.market_structure import TrendContinuationConfig
        obj=TrendContinuationConfig()
    elif spec and spec.adapter=='library':
        from trading.tested_strategy_research import strategy_details
        lib=strategy_details(spec.source)
        obj=lib.factory().config if lib else None
    else: obj=None
    if obj is not None and is_dataclass(obj):
        return {f.name:getattr(obj,f.name) for f in fields(obj) if isinstance(getattr(obj,f.name),(int,float,bool,time,date))}
    return {}

def normalize(values,defaults):
    if set(values)-set(defaults): raise ValueError('Unknown engine setting')
    out={}
    for name,value in values.items():
        default=defaults[name]
        if isinstance(default,bool):
            if type(value) is not bool: raise ValueError(f'{name}: choose on or off')
        elif isinstance(default,time):
            try: value=time.fromisoformat(value)
            except (ValueError,TypeError): raise ValueError(f'{name}: use HH:MM Eastern')
            if value.tzinfo or value.second or value.microsecond: raise ValueError(f'{name}: use HH:MM Eastern')
        elif isinstance(default,date):
            try:value=date.fromisoformat(value)
            except (ValueError,TypeError):raise ValueError(f'{name}: use YYYY-MM-DD')
        elif isinstance(default,(int,float)):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError(f'{name}: enter a finite number')
            if isinstance(default,int):
                if int(value)!=value or not 1<=value<=2000: raise ValueError(f'{name}: use a whole number from 1 to 2000')
                value=int(value)
            elif not 0<=value<=1000: raise ValueError(f'{name}: use a number from 0 to 1000')
        out[name]=value
    merged={**defaults,**out}
    for a,b in [('fast_ema','slow_ema'),('macd_fast','macd_slow'),('entry_start','entry_end'),('start','end'),('start_time','end_time'),('pullback_min_atr','pullback_max_atr'),('min_gap_pct','max_gap_pct'),('min_range_pct','max_range_pct')]:
        if a in merged and b in merged and merged[a]>=merged[b]: raise ValueError(f'{a} must be below {b}')
    return out

@contextmanager
def for_pair(settings,sid,ticker):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule=REVIEWED_STRATEGIES.get(sid)
    saved=(settings.get(KEY) or {}).get(scope_key(settings,sid,ticker,rule.version)) if rule else None
    values=normalize(saved.get('entry',{}),definition(sid)) if saved else {}
    token=_current.set({'entry':values,'revision':saved.get('revision')} if saved else None)
    try: yield
    finally: _current.reset(token)

def parameter(name,default):
    return ((_current.get() or {}).get('entry') or {}).get(name,default)

def configured(obj):
    values=(_current.get() or {}).get('entry') or {}
    if not values:return obj
    if not is_dataclass(obj):return obj
    return replace(obj,**{f.name:values[f.name] for f in fields(obj) if f.name in values})

def configure_engine(engine):
    if hasattr(engine,'config'):
        changed=configured(engine.config)
        if changed != engine.config:
            engine=type(engine)(changed)
        if (_current.get() or {}).get('revision'):
            engine._configuration_revision=_current.get()['revision']
    return engine

def attach(signal):
    state=_current.get()
    if signal is not None and state and state.get('revision'):
        signal.meta['engine_configuration']={'revision':state['revision'],'entry':{k:encode(v) for k,v in state['entry'].items()}}
    return signal

def describe(settings,sid,ticker,version):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from config.research_order_specs import SPECS
    rule=REVIEWED_STRATEGIES.get(sid)
    if not rule or rule.version!=version:raise ValueError('Strategy version changed. Reload Settings.')
    ticker=ticker.upper()
    import re
    if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}',ticker):raise ValueError('Invalid ticker')
    spec=SPECS.get(sid)
    allowed=spec.allowed_tickers if spec else rule.tickers
    if allowed and ticker not in allowed:raise ValueError('Ticker is not supported by this strategy')
    defaults=definition(sid)
    saved=(settings.get(KEY) or {}).get(scope_key(settings,sid,ticker,version),{})
    current={**defaults,**normalize(saved.get('entry',{}),defaults)}
    from trading.premium_policy import freeze_selection
    policy_warning=None
    try:policy=freeze_selection(settings,sid,ticker,version).get('premium_exit_policy')
    except ValueError as exc:
        if str(exc)!='The assigned exit changed. Review and save this ticker configuration again.':raise
        policy_warning=str(exc)
        clean={**settings,KEY:{**(settings.get(KEY) or {}),scope_key(settings,sid,ticker,version):{k:v for k,v in saved.items() if k!='profit'}}}
        policy=freeze_selection(clean,sid,ticker,version).get('premium_exit_policy')
    from config.research_pair_policy import selected
    from config.strategy_catalog import reviewed_exit_summary
    return {'strategy_id':sid,'ticker':ticker,'version':version,'mode':'paper' if settings.get('paper_trading',True) else 'live',
            'revision':revision(saved),'entry':[{'key':k,'label':k.replace('_',' ').capitalize(),
             'value':encode(v),'default':encode(defaults[k]),'type':'boolean' if isinstance(v,bool) else 'time' if isinstance(v,time) else 'date' if isinstance(v,date) else 'number'} for k,v in current.items()],
            'policy_warning':policy_warning,'exit_policy':policy,'selected_contract_timer':selected(settings,sid,ticker,version),
            'native_exit':reviewed_exit_summary(sid),
            'profit_overrides':None if policy_warning else saved.get('profit'), 'contract_timer_overrides':saved.get('contract_timer'),
            'contract_editable':sid in SPECS,
            'account_risk':{k:settings.get(k) for k in RISK_KEYS},
            'risk': {k: saved.get('risk',{}).get(k,settings.get(k)) for k in RISK_KEYS}, 'risk_overrides':saved.get('risk',{}),
            'entry_editable':bool(defaults)}

def save(settings,sid,ticker,version,expected,entry,actor,risk=None,profit=None,contract_timer=None):
    view=describe(settings,sid,ticker,version)
    if view['revision']!=expected:raise RuntimeError('Settings changed in another session. Reload before saving.')
    parsed=normalize(entry,definition(sid))
    validate_engine(sid,parsed)
    key=scope_key(settings,sid,ticker,version)
    stored={**(settings.get(KEY) or {})}
    content={'risk':validate_risk(risk or {}),'entry':{k:encode(v) for k,v in parsed.items()},'actor':actor,'updated_at':datetime.now(timezone.utc).isoformat()}
    if profit is not None:
        from trading.premium_policy import scope, fingerprint
        assigned=(settings.get('premium_exit_paper_assignments') or {}).get(scope(settings.get('active_broker_account_id'),sid,ticker,version))
        if settings.get('paper_trading') is not True or not assigned or assigned.get('rule')!='trend_partial_profit' or not assigned.get('replace_native_exit'):
            raise ValueError('This pair does not have an assigned paper partial-profit exit')
        content['profit']=validate_profit(profit)
        content['base_policy_fingerprint']=assigned['fingerprint']
    if contract_timer is not None:
        from config.research_pair_policy import build
        if set(contract_timer)-{'exit_minutes','contract_policy'}:raise ValueError('Unsupported contract or timer field')
        if view['exit_policy'] and view['exit_policy'].get('replace_native_exit') and contract_timer.get('exit_minutes') is not None:
            raise ValueError('The active profit exit replaces the timer. Do not add another timer.')
        content['contract_timer']=build(sid,ticker,version,contract_timer.get('exit_minutes'),contract_timer.get('contract_policy'))
    content['revision']=revision(content)
    stored[key]=content
    return {KEY:stored}

# Entry sizing overrides are read only after a strategy has supplied a setup.
# Account safety limits remain account-wide and cannot be weakened here.
_sizing = ContextVar('entry_sizing', default=None)
RISK_KEYS = {'risk_per_trade','max_position_dollars_pct'}

def entry_cycle(fn):
    from functools import wraps
    @wraps(fn)
    def wrapped(*args,**kwargs):
        token=_sizing.set(None)
        try:return fn(*args,**kwargs)
        finally:_sizing.reset(token)
    return wrapped

def select_sizing(settings,sid,ticker):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from auth.context import get_current_user_id
    rule=REVIEWED_STRATEGIES.get(sid)
    saved=(settings.get(KEY) or {}).get(scope_key(settings,sid,ticker,rule.version),{}) if rule else {}
    values=saved.get('risk',{})
    _sizing.set((get_current_user_id(),values))
    return {**settings,**values}

def sizing_settings(settings,uid):
    current=_sizing.get()
    if current and current[0]==uid:return {**settings,**current[1]}
    return settings

def validate_risk(values):
    if set(values)-RISK_KEYS:raise ValueError('Unsupported per-ticker risk setting')
    for key,value in values.items():
        if key=='risk_per_trade' and value is None:continue
        maximum=1 if key=='risk_per_trade' else 100
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<value<=maximum:
            raise ValueError(f'{key}: value must be greater than zero and at most {maximum}')
    return values

def validate_profit(values):
    from trading.trend_profit_exit import valid_thresholds
    from trading.adverse_candle_exit import validate
    if not isinstance(values,dict) or set(values) != {'gain_pct','giveback_pct','adverse_candle_failsafe'}:
        raise ValueError('Profit settings must include gain, giveback and the candle fail-safe')
    policy={**values,'configuration_editor':1}
    if not valid_thresholds(policy):raise ValueError('Profit gain must be above 0% and at most 1000%; giveback above 0% and at most 99%')
    validate(policy)
    return values

def profit_selection(settings,sid,ticker,version,assignment):
    saved=(settings.get(KEY) or {}).get(scope_key(settings,sid,ticker,version),{})
    values=saved.get('profit')
    if values is None:return assignment
    from trading.premium_policy import fingerprint
    if assignment.get('fingerprint') != fingerprint(assignment):
        raise ValueError('Invalid original policy fingerprint')
    if saved.get('base_policy_fingerprint')!=assignment.get('fingerprint'):
        raise ValueError('The assigned exit changed. Review and save this ticker configuration again.')
    from trading.premium_policy import fingerprint
    if settings.get('paper_trading') is not True or assignment.get('rule')!='trend_partial_profit':
        raise ValueError('Editable profit settings require the existing paper partial-profit exit')
    out={**assignment,**validate_profit(values),'configuration_editor':1,'configuration_revision':saved['revision']}
    out['fingerprint']=fingerprint(out)
    return out

CONTEXT_DEFAULTS={
 'CTX_ORB_NR7_OR_INSIDE':{'volume_ratio_minimum':1.5,'narrow_range_days':7},
 'CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG':{'volume_ratio_minimum':1.5,'daily_atr_period':10},
 'CTX_VWAP_PULLBACK_KER10_LONG':{'reclaim_ema_period':9,'efficiency_period':10,'efficiency_minimum':.60},
 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG':{'reclaim_ema_period':9,'displacement_fraction':.01},
 'CTX_1H_SQUEEZE_MACD_LONG':{'macd_fast':12,'macd_slow':26,'macd_signal':9,'band_period':20,'band_deviations':2.0,'channel_atr_multiple':1.5},
}


def validate_engine(sid, values):
    """Run the engine's own validation before accepting a saved configuration."""
    from config.research_order_specs import SPECS
    spec=SPECS.get(sid)
    if spec and spec.adapter=='library':
        from trading.tested_strategy_research import strategy_details
        engine=strategy_details(spec.source).factory()
        replace(engine.config,**values)
    elif sid=='V2_TREND_CONT':
        from research.engine.strategies.trend_continuation import TrendContinuationConfig
        replace(TrendContinuationConfig(),**values)
    elif sid in ('V2_SPY_TREND_CONT','RESEARCH_QQQ_TREND_V2') or (spec and spec.adapter=='native_trend'):
        from strategies.market_structure import TrendContinuationConfig
        replace(TrendContinuationConfig(),**values)
    merged={**definition(sid),**values}
    for key,value in merged.items():
        if isinstance(value,bool):continue
        if key in ('efficiency_minimum','displacement_fraction') and not 0<value<1:
            raise ValueError(f'{key}: use a fraction between zero and one')
        if key in ('reclaim_ema_period','daily_atr_period','band_period','fast_ema','slow_ema','atr_bars') and value<2:
            raise ValueError(f'{key}: use at least 2')
