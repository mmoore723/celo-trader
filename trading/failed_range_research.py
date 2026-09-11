"""Research every fresh failed-range episode, never create orders.

Consume a breakout once its opposite-colour return occurs (including a return
with insufficient VWAP room). A subsequent outside close starts a new episode.
The original excursion, time, colour, stop and target rules are unchanged.
"""
from datetime import time, timedelta
import math
import pandas as pd

from strategies import spy_failed_range_recovery_v2 as source
from strategies.base import Signal
from strategies.market_structure import Side, _atr, _ema, _opening_range
from strategies.price_action_context import describe_price_action
from trading.research_versions import evidence_version

STRATEGY_ID = source.STRATEGY_ID
POLICY = 'fresh_failed_range_episodes_v2'
_last_trigger = {}


def latest_candidate(bars):
    opening = _opening_range(bars)
    if not opening or opening[0] <= opening[1]:
        return None
    high, low = opening
    width = high-low
    side = anchor = None
    pv = volume = 0.0
    candidate = None
    for bar in bars:
        weight = max(bar.volume, 1.0)
        pv += (bar.high+bar.low+bar.close)/3*weight
        volume += weight
        candidate = None  # Only a failure on the newest completed bar can emit.
        clock = bar.timestamp.time()
        if clock < time(9,45):
            continue
        if side is None:
            if clock > source.BREAKOUT_DEADLINE:
                continue
            excursion = width*source.MINIMUM_EXCURSION_RANGE
            if bar.close >= high+excursion:
                side, anchor = Side.LONG, bar
            elif bar.close <= low-excursion:
                side, anchor = Side.SHORT, bar
            continue
        if clock > source.FAILURE_DEADLINE:
            continue
        failed_up = side is Side.LONG and bar.close <= high and bar.close < bar.open
        failed_down = side is Side.SHORT and bar.close >= low and bar.close > bar.open
        if not (failed_up or failed_down):
            continue
        vwap, room = pv/volume, width*source.MINIMUM_VWAP_ROOM_RANGE
        if failed_up and bar.close-vwap >= room:
            stop = max(anchor.high,bar.high)+width*source.STOP_BUFFER_RANGE
            candidate = (Side.SHORT,bar,stop,vwap,high,low,anchor)
        elif failed_down and vwap-bar.close >= room:
            stop = min(anchor.low,bar.low)-width*source.STOP_BUFFER_RANGE
            candidate = (Side.LONG,bar,stop,vwap,high,low,anchor)
        side = anchor = None
    return candidate


def evaluate(today, *, ticker, scope, now=None):
    if not scope.startswith('research_worker:'):
        raise ValueError('Failed-range expansion is restricted to the research worker')
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='America/New_York')
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert('America/New_York').tz_localize(None)
    prices = pd.DataFrame(today)  # Do not copy multi-session attrs on each price operation.
    if prices.empty or not {'time','open','high','low','close'}.issubset(prices.columns):
        return None
    times = pd.to_datetime(prices['time'])
    if times.dt.tz is not None:
        times = times.dt.tz_convert('America/New_York').dt.tz_localize(None)
    prices = prices.assign(time=times)
    prices = prices.loc[(times.dt.date == cutoff.date()) & (times < cutoff.floor('min'))]
    try:
        bars = source._completed_one_minute_bars(prices, now=cutoff)
        if any(not all(math.isfinite(x) for x in (b.open,b.high,b.low,b.close,b.volume))
               or not (0 < b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high and b.volume >= 0)
               for b in bars):
            return None
    except (TypeError,ValueError):
        return None
    candidate = latest_candidate(bars)
    if candidate is None:
        return None
    side, trigger, stop, target, high, low, anchor = candidate
    stamp = pd.Timestamp(trigger.timestamp)
    visible = stamp+timedelta(minutes=1)
    if not visible <= cutoff < visible+timedelta(minutes=1):
        return None
    key = (scope,ticker.strip().upper())
    if _last_trigger.get(key) == stamp:
        return None
    closes = [b.close for b in bars[-20:]]
    atr = _atr(bars,14)
    features = describe_price_action(bars,atr=atr,fast_ema=_ema(closes[-8:],8),
        slow_ema=_ema(closes,20),vwap=source._session_vwap(bars)).features() if atr > 0 else {}
    from config.strategy_catalog import REVIEWED_STRATEGIES
    signal = Signal(strategy_id=STRATEGY_ID,direction='bullish' if side is Side.LONG else 'bearish',
        confidence=.8,rvol=float(prices.sort_values('time').iloc[-1].get('rvol',0) or 0),
        trigger_bar=stamp,meta={**features,
            'trigger':'downward_opening_range_break_failed_back_inside' if side is Side.LONG else 'upward_opening_range_break_failed_back_inside',
            'or_high':round(high,6),'or_low':round(low,6),'vwap':round(target,6),
            'v2_entry_reference':float(trigger.close),'v2_stop':float(stop),'v2_target':float(target),
            'entry_bar_low':float(trigger.low) if side is Side.LONG else None,
            'entry_bar_high':float(trigger.high) if side is Side.SHORT else None,
            'entry_timing':'completed_1m_failure_then_next_1m_entry','reviewed_exit_minutes':30,
            'observation_only':True,'research_emission_policy':POLICY,
            'research_episode_anchor':pd.Timestamp(anchor.timestamp).isoformat(),
            'strategy_version':evidence_version(STRATEGY_ID,REVIEWED_STRATEGIES[STRATEGY_ID].version),
            'implementation':'trading.failed_range_research'})
    _last_trigger[key] = stamp
    return signal
