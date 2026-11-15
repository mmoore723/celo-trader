"""Declared per-strategy mechanics. Defaults reproduce existing behavior."""
from datetime import time, datetime, timedelta

INTERVALS=(1,2,3,4,5,10,15,20,30,60)

def source_id(sid):
    from config.research_order_specs import SPECS
    return SPECS[sid].source if sid in SPECS else sid

def defaults(sid):
    from config.research_order_specs import SPECS
    source=source_id(sid)
    spec=SPECS.get(sid)
    from trading.tested_strategy_research import strategy_details
    library=strategy_details(source)
    tf=library.timeframe_minutes if library else (spec.timeframe if spec else 5)
    if source in ('V2_ORB_PULLBACK','V2_FAILED_OR_BREAK_VWAP_REVERSION','V2_TSLA_TWO_LEG_TREND_PULLBACK'):tf=1
    if source.startswith('CTX_ORB'):tf=1
    if source=='CTX_1H_SQUEEZE_MACD_LONG':tf=60
    result={'entry_timeframe_minutes':tf}
    # Gate only directions that the existing strategy can generate. No synthetic opposite-side rule.
    result['allow_long']=source!='V2_SPY_ORB_RSI_MACD_SHORT'
    result['allow_short']=source not in ('V2_ORB_PULLBACK','CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG','CTX_VWAP_PULLBACK_KER10_LONG','CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG','CTX_1H_SQUEEZE_MACD_LONG','V2_SPY_ORB_RSI_MACD_SHORT')
    if source=='V2_SPY_ORB_RSI_MACD_SHORT':result['allow_short']=True
    if source in ('V2_ORB_PULLBACK','V2_FAILED_OR_BREAK_VWAP_REVERSION') or source.startswith('CTX_ORB'):
        result.update(opening_range_minutes=15)
    if source=='V2_TSLA_TWO_LEG_TREND_PULLBACK':result.update(stop_atr_multiple=1.,require_directional_confirmation=True)
    if source=='V2_ORB_PULLBACK':result.update(reward_risk=2.,stop_range_fraction=1.,minimum_retouch_dollars=.01)
    if source=='V2_SPY_AFTERNOON_FVG':result.update(stop_atr_multiple=1.,reward_risk=2.,require_first_retest=True,require_midpoint_close=True)
    if source.startswith('CTX_ORB'):
        result.update(entry_start=time(9,45),entry_end=time(11),volume_lookback_bars=20,midpoint_fraction=.5)
    if source.startswith('CTX_VWAP'):
        result.update(entry_start=time(9,45),entry_end=time(16),displacement_checkpoint=time(10,30),context_timeframe_minutes=60,prior_extreme_lookback_bars=2000)
    if source=='CTX_VWAP_PULLBACK_KER10_LONG':result.pop('displacement_checkpoint')
    if source=='CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG':result.pop('context_timeframe_minutes')
    if source in ('V2_RANGE_SWEEP_RECLAIM','V2_MIDDAY_BREAKDOWN','CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG','CTX_VWAP_PULLBACK_KER10_LONG','CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG','CTX_1H_SQUEEZE_MACD_LONG','V2_SPY_ORB_RSI_MACD_SHORT'):
        result.pop('allow_long');result.pop('allow_short')
    if source=='V2_FAILED_OR_BREAK_VWAP_REVERSION':result.update(vwap_target_fraction=1.)
    return result

def validate_inputs(sid,values):
    merged={**defaults(sid),**values}
    for key in ('entry_timeframe_minutes','context_timeframe_minutes'):
        if key in merged and merged[key] not in INTERVALS:raise ValueError(key+': choose 1, 2, 3, 4, 5, 10, 15, 20, 30 or 60 minutes')
    if 'opening_range_minutes' in merged and not 1<=merged['opening_range_minutes']<=120:raise ValueError('Opening range must be 1 to 120 minutes')
    for key in ('stop_range_fraction','midpoint_fraction','vwap_target_fraction'):
        if key in merged and not 0<merged[key]<=1:raise ValueError(key+': must be above zero and at most 1')
    n=merged['entry_timeframe_minutes']
    if source_id(sid)=='V2_TSLA_TWO_LEG_TREND_PULLBACK':
        checkpoint=merged.get('reference_time',time(9,45))
        if (checkpoint.hour*60+checkpoint.minute-570)%n:raise ValueError('Reference time must align with the entry candle interval, measured from 9:30 Eastern')
    if 'displacement_checkpoint' in merged:
        checkpoint=merged['displacement_checkpoint']
        if (checkpoint.hour*60+checkpoint.minute-570)%n:raise ValueError('Displacement checkpoint must align with a completed entry candle, measured from 9:30 Eastern')
    for key in ('reward_risk','stop_atr_multiple','minimum_retouch_dollars'):
        if key in merged and merged[key]<=0:raise ValueError(key+': must be positive')
    if not merged.get('allow_long',True) and not merged.get('allow_short',True):raise ValueError('Allow at least one direction; use Pause to disable the pair')

def allows(direction):
    from config.engine_parameters import parameter
    return parameter('allow_long' if direction=='bullish' else 'allow_short',True)

def opening_end():
    from config.engine_parameters import parameter
    return (datetime(2000,1,1,9,30)+timedelta(minutes=parameter('opening_range_minutes',15))).time()


def aggregate_entry_bars(bars, *, keep_opening=False):
    """Aggregate complete input minutes only; opening range retains its minute evidence."""
    from config.engine_parameters import parameter
    from strategies.market_structure import resample_regular_session, Bar
    n=parameter('entry_timeframe_minutes',1)
    if n==1:return bars
    converted=tuple(Bar(b.timestamp,b.open,b.high,b.low,b.close,b.volume) for b in bars)
    result=resample_regular_session(converted,source_minutes=1,target_minutes=n)
    if keep_opening:
        return tuple(b for b in converted if b.timestamp.time()<opening_end())+tuple(b for b in result if b.timestamp.time()>=opening_end())
    return result
