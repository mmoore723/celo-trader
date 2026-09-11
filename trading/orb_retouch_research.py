"""Observe each distinct long breakout/retouch episode; never place orders."""
import hashlib
import math
import pandas as pd
from strategies.base import Signal
from strategies.market_structure import OpeningRangeBreakoutContext, Side, _opening_range, _atr, _ema, retouch_status
from strategies.price_action_context import describe_price_action
from trading import orb_retouch_execution as source
from trading.research_versions import evidence_version

STRATEGY_ID = source.STRATEGY_ID
POLICY = 'fresh_orb_retouch_episodes_v2'


def latest_episode(bars):
    opening = _opening_range(bars)
    if not opening or opening[0] <= opening[1]:
        return None
    high,low = opening
    context, previous_side = None, 0
    tolerance = max(high*source.RETOUCH_TOLERANCE_PCT,.01)
    for bar in bars:
        if not pd.Timestamp('09:45').time() <= bar.timestamp.time() <= source.ENTRY_DEADLINE:
            continue
        side = 1 if bar.close > high else -1 if bar.close < low else 0
        if side and side != previous_side:
            context = OpeningRangeBreakoutContext(Side.LONG if side==1 else Side.SHORT,
                high,low,bar.timestamp,bar.close)
        elif context is not None and context.side is Side.LONG and bar.close < high-tolerance:
            context = None  # A completed fall through is not a delayed retouch.
        previous_side = side
    return context


def update(state,today,*,ticker,quote,now,scope):
    if not scope.startswith('research_worker:'):
        raise ValueError('ORB expansion is restricted to the research worker')
    now = pd.Timestamp(now)
    now = now.tz_localize('America/New_York') if now.tzinfo is None else now.tz_convert('America/New_York')
    if now.time()>source.ENTRY_DEADLINE:
        return None,'entry_window_expired'
    prices = pd.DataFrame(today)
    if prices.empty or not {'time','open','high','low','close'}.issubset(prices.columns):
        return None,'waiting_for_bars'
    times = pd.to_datetime(prices['time'])
    times = times.dt.tz_localize('America/New_York') if times.dt.tz is None else times.dt.tz_convert('America/New_York')
    prices = prices.assign(time=times).loc[(times.dt.date==now.date()) & (times.dt.time>=pd.Timestamp('09:30').time())]
    bars = source._completed_bars(prices,now)
    if not bars or (now-pd.Timestamp(bars[-1].timestamp)).total_seconds()>=180:
        return None,'waiting_for_current_bars'
    if any(not all(math.isfinite(n) for n in (b.open,b.high,b.low,b.close,b.volume)) or
           not (0<b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high and b.volume>=0) for b in bars):
        return None,'invalid_candles'
    context = latest_episode(bars)
    if context is None:
        return None,'building_or_waiting_for_breakout'
    if context.side is not Side.LONG:
        return None,'waiting_for_long_breakout'  # No day-long lockout after a short break.
    key = (scope,ticker.strip().upper())
    if state.get(key,{}).get('day') != now.date().isoformat():
        state[key] = {'day':now.date().isoformat(),'consumed':set()}
    consumed = state[key]['consumed']
    anchor = pd.Timestamp(context.breakout_time).isoformat()
    if anchor in consumed:
        return None,'already_observed_episode'
    try:
        ask,bid = float(quote['ap']),float(quote['bp'])
        quote_at = pd.Timestamp(quote['t'])
        if quote_at.tzinfo is None or not all(math.isfinite(p) for p in (ask,bid)) or not 0<bid<=ask:
            return None,'invalid_quote'
        if not 0 <= (now-quote_at).total_seconds() <= 60 or quote_at < pd.Timestamp(context.breakout_time)+pd.Timedelta(minutes=1):
            return None,'stale_or_pre_breakout_quote'
    except (KeyError,TypeError,ValueError):
        return None,'quote_unavailable'
    price = (ask+bid)/2
    status = retouch_status(context,price,tolerance_pct=source.RETOUCH_TOLERANCE_PCT)
    if status == 'ready':
        return None,'armed_waiting_for_first_retouch'
    consumed.add(anchor)
    if status == 'failed':
        return None,'failed_retouch'
    stop = context.range_low
    risk = price-stop
    if risk<=0:
        return None,'invalid_risk'
    features = {}
    if len(bars)>=20:
        atr = _atr(bars,14)
        closes = [b.close for b in bars[-20:]]
        weights = [max(float(b.volume),1.) for b in bars]
        vwap = sum((b.high+b.low+b.close)/3*w for b,w in zip(bars,weights))/sum(weights)
        if atr>0:
            features = describe_price_action(bars,atr=atr,fast_ema=_ema(closes[-9:],9),slow_ema=_ema(closes,20),vwap=vwap).features()
    from config.strategy_catalog import REVIEWED_STRATEGIES
    version = evidence_version(STRATEGY_ID,REVIEWED_STRATEGIES[STRATEGY_ID].version)
    play_key = hashlib.sha256(f'{scope}|{ticker.upper()}|{STRATEGY_ID}|{version}|{anchor}'.encode()).hexdigest()
    return Signal(confidence=.8,strategy_id=STRATEGY_ID,direction='bullish',rvol=float(prices.iloc[-1].get('rvol',0) or 0),
        trigger_bar=now,meta={**features,'v2_hypothesis':'one_minute_opening_range_long_retouch_before_1030',
            'entry_timing':'completed_1m_breakout_then_live_quote_first_retouch',
            'or_high':context.range_high,'or_low':context.range_low,'breakout_time':anchor,
            'retest_level':context.retouch_level,'quote_entry_reference':price,'v2_entry_reference':price,
            'v2_stop':stop,'v2_target':price+2*risk,'entry_bar_low':stop,'entry_bar_high':None,
            'research_episode_anchor':anchor,'research_play_key':play_key,'observation_only':True,
            'research_emission_policy':POLICY,'strategy_version':version,
            'underlying_quote_at':quote_at.isoformat(),'implementation':'trading.orb_retouch_research'}),'first_retouch_quote'
