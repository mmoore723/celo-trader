"""All eligible completed context entries, exclusively for the research worker.

The reviewed order implementation remains untouched. Its entry math and exit
levels are retained here, but an earlier eligible bar cannot stop a later one.
Only the newest completed bar can trigger; old signals are never repriced now.
"""
from datetime import time, timedelta
import math
import pandas as pd

from strategies import context_strategy_observers as source
from strategies.base import Signal
from trading.research_versions import evidence_version

POLICY = 'completed_context_entries_v2'
STRATEGY_IDS = frozenset((source.ORB_NR7_INSIDE, source.ORB_ATR10_LONG,
                         source.VWAP_KER10_LONG, source.VWAP_DISPLACEMENT_LONG))
_last_trigger = {}


def _orb(today, strategy_id, now, history):
    rows = source._completed_today(today, now)
    if rows.empty or history.empty:
        return None
    opening = rows.loc[(rows['time'].dt.time >= time(9,30)) &
                       (rows['time'].dt.time < time(9,45))]
    expected = [opening.iloc[0]['time'].replace(hour=9,minute=30,second=0,microsecond=0)
                + timedelta(minutes=i) for i in range(15)] if not opening.empty else []
    if len(opening) != 15 or opening['time'].tolist() != expected:
        return None
    gate = source._nr7_inside_gate if strategy_id == source.ORB_NR7_INSIDE else source._atr10_gate
    allowed, context = gate(source._daily_context(history, rows.iloc[-1]['time'].date()))
    if not allowed or len(rows) < 21:
        return None
    bar = rows.iloc[-1]
    if not time(9,45) <= bar['time'].time() <= time(11):
        return None
    average = float(rows.iloc[-21:-1]['volume'].mean())
    ratio = float(bar['volume']) / average if average > 0 else 0.0
    if ratio <= 1.5:
        return None
    high, low = float(opening['high'].max()), float(opening['low'].min())
    direction = ('bullish' if float(bar['close']) > high else
                 'bearish' if strategy_id == source.ORB_NR7_INSIDE and float(bar['close']) < low else None)
    if direction is None:
        return None
    return Signal(confidence=.8, strategy_id=strategy_id, direction=direction,
        rvol=float(bar.get('rvol',0) or 0), trigger_bar=pd.Timestamp(bar['time'])+timedelta(minutes=1),
        meta={**context, 'or_high':round(high,6), 'or_low':round(low,6),
              'or_midpoint':round((high+low)/2,6), 'volume_ratio_20':round(ratio,6),
              'entry_timing':'completed_1m_breakout_then_next_quote',
              'exit_plan':'30% partial, 100% runner, or 1m close through opening-range midpoint'})


def _vwap(today, strategy_id, now, history):
    five = source._complete_five_minute_bars(today, now=now)
    if len(five) < 2 or history.empty:
        return None
    session = [bar for bar in five if bar.timestamp.date() == five[-1].timestamp.date()]
    pv = volume = 0.0
    vwaps = []
    for bar in session:
        weight = max(float(bar.volume),1.0)
        pv += ((bar.high+bar.low+bar.close)/3)*weight
        volume += weight
        vwaps.append(pv/volume)
    index = len(session)-1
    bar = session[index]
    if index < 1 or bar.timestamp.time() < time(9,45):
        return None
    ema9 = source._ema([item.close for item in session[max(0,index-8):index+1]],9)
    vwap = vwaps[index]
    if not (session[index-1].close > vwaps[index-1] and bar.low <= vwap and bar.close > ema9):
        return None
    previous_high = max(item.high for item in session[:index])
    if previous_high <= bar.close:
        return None
    visible = pd.Timestamp(bar.timestamp)+timedelta(minutes=5)
    ker = source._kaufman([item['close'] for item in source._hourly(history,visible)],10)
    displacement = any(item.timestamp.time() == time(10,25) and item.close >= vwaps[i]*1.01
                       for i,item in enumerate(session))
    allowed = (ker is not None and ker > .60 if strategy_id == source.VWAP_KER10_LONG
               else displacement and bar.timestamp.time() >= time(10,30))
    if not allowed:
        return None
    return Signal(confidence=.8,strategy_id=strategy_id,direction='bullish',rvol=0.0,
        trigger_bar=visible,meta={'vwap':round(vwap,6),'ema9':round(ema9,6),
            'previous_high':round(previous_high,6),'ker_1h_10':round(float(ker or 0),6),
            'displacement_at_1030':displacement,
            'entry_timing':'completed_5m_touch_reclaim_then_next_quote',
            'exit_plan':'previous high target or first 5m close below session VWAP'})


def evaluate(today, *, strategy_id, ticker, scope, now=None):
    if strategy_id not in STRATEGY_IDS or not scope.startswith('research_worker:'):
        raise ValueError('Context expansion is restricted to the research worker')
    required = {'time','open','high','low','close','volume'}
    if today.empty or not required.issubset(today.columns):
        return None
    history = source._history_frame(today)
    # Pandas propagates attrs with deep copies on ordinary column/row access.
    # Keep the immutable context tape out of price operations, not out of the
    # signal's context checks. The constructor retains values, not attrs.
    prices = pd.DataFrame(today)
    try:
        for row in prices.itertuples(index=False):
            o,h,low,c,v = (float(getattr(row,k)) for k in ('open','high','low','close','volume'))
            if not all(math.isfinite(n) for n in (o,h,low,c,v)) or not (0<low<=min(o,c)<=max(o,c)<=h and v>=0):
                return None
    except (TypeError,ValueError):
        return None
    candidate = (_orb(prices,strategy_id,now,history) if strategy_id in {source.ORB_NR7_INSIDE,source.ORB_ATR10_LONG}
                 else _vwap(prices,strategy_id,now,history))
    if candidate is None:
        return None
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='America/New_York')
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert('America/New_York').tz_localize(None)
    # One-minute collection may observe a completed 5m bar between scans.
    # Never backfill its option entry using a quote more than one minute late.
    if not candidate.trigger_bar <= cutoff < candidate.trigger_bar+timedelta(minutes=1):
        return None
    key = (scope,ticker.upper(),strategy_id)
    if _last_trigger.get(key) == candidate.trigger_bar:
        return None
    from config.strategy_catalog import REVIEWED_STRATEGIES
    candidate.meta.update(observation_only=True,research_emission_policy=POLICY,
                          strategy_version=evidence_version(strategy_id,REVIEWED_STRATEGIES[strategy_id].version),
                          implementation='trading.context_research_entries')
    _last_trigger[key] = candidate.trigger_bar
    return candidate
