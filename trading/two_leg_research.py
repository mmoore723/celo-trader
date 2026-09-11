"""Fresh two-leg episodes for research only; reviewed order code is untouched."""
import math
import pandas as pd
from strategies.base import Signal
from trading import two_leg_trend_pullback_execution as source
from trading.research_versions import evidence_version

STRATEGY_ID = source.STRATEGY_ID
POLICY = 'fresh_two_leg_episodes_v2'


def latest_candidate(bars):
    if not bars:
        return None
    reference = source._reference_close(list(bars))
    leg = None
    for index,current in enumerate(bars):
        if not source.ENTRY_START <= current.timestamp.time() <= source.ENTRY_END or index+1 < max(source.SLOW_EMA,source.ATR_BARS+1) or reference is None:
            continue
        history = list(bars[:index+1])
        closes = [b.close for b in history[-source.SLOW_EMA:]]
        fast = source._ema(closes[-source.FAST_EMA:],source.FAST_EMA)
        slow = source._ema(closes,source.SLOW_EMA)
        atr, vwap = source._atr(history,source.ATR_BARS), source._vwap(history)
        if atr <= 0:
            continue
        had_leg = leg is not None
        if leg is not None:
            if index-leg.impulse_index > source.PULLBACK_LIMIT_BARS:
                leg = None
            else:
                bullish = leg.direction == 'bullish'
                previous = bars[index-1]
                leg.impulse_extreme = (max(leg.impulse_extreme,current.high) if bullish
                                       else min(leg.impulse_extreme,current.low))
                retrace = leg.impulse_extreme-current.low if bullish else current.high-leg.impulse_extreme
                invalid = (current.close <= vwap or fast <= slow) if bullish else (current.close >= vwap or fast >= slow)
                if invalid or retrace > source.PULLBACK_MAX_ATR*atr:
                    leg = None
                elif leg.pullback_extreme is None:
                    if retrace >= source.PULLBACK_MIN_ATR*atr and (current.low <= fast if bullish else current.high >= fast):
                        leg.pullback_extreme = current.low if bullish else current.high
                else:
                    leg.pullback_extreme = (min(leg.pullback_extreme,current.low) if bullish
                                            else max(leg.pullback_extreme,current.high))
                    reclaim = (current.close > previous.high and current.close > fast if bullish
                               else current.close < previous.low and current.close < fast)
                    if reclaim:
                        context = source.describe_price_action(history,atr=atr,fast_ema=fast,slow_ema=slow,vwap=vwap)
                        stop = min(leg.pullback_extreme,current.close-atr) if bullish else max(leg.pullback_extreme,current.close+atr)
                        risk = current.close-stop if bullish else stop-current.close
                        if source._has_directional_confirmation(context,leg.direction) and risk > 0 and index == len(bars)-1:
                            return Signal(confidence=.8,strategy_id=STRATEGY_ID,direction=leg.direction,rvol=current.rvol,
                                trigger_bar=current.timestamp,meta={**context.features(),
                                    'v2_hypothesis':'two_leg_impulse_vwap_hold_pullback_1m_reclaim',
                                    'validated_entry_rule':'after_0945_vwap_ema_aligned_1atr_impulse_pullback_fast_ema_then_directionally_confirmed_completed_1m_reclaim',
                                    'entry_timing':'completed_1m_reclaim_then_next_1m_option_ask','directional_confirmation':True,
                                    'reference_945':round(reference,6),'vwap':round(vwap,6),
                                    'fast_ema':round(fast,6),'slow_ema':round(slow,6),'atr':round(atr,6),
                                    'impulse_extreme':round(leg.impulse_extreme,6),
                                    'pullback_low' if bullish else 'pullback_high':round(leg.pullback_extreme,6),
                                    'reclaim_level':round(previous.high if bullish else previous.low,6),
                                    'v2_entry_reference':round(current.close,6),'v2_stop':round(stop,6),
                                    'v2_target':round(current.close+(1 if bullish else -1)*source.REWARD_RISK*risk,6),
                                    'pullback_min_atr':source.PULLBACK_MIN_ATR,'pullback_max_atr':source.PULLBACK_MAX_ATR,
                                    'research_episode_anchor':bars[leg.impulse_index].timestamp.isoformat()})
                        # A completed reclaim consumes this episode, even if
                        # confirmation failed. A later candle must start a NEW
                        # impulse; it cannot rescue the rejected reclaim.
                        leg = None
        if leg is None and not had_leg:
            if current.close > vwap and fast > slow and current.close-reference >= source.IMPULSE_ATR*atr:
                leg = source._Leg('bullish',current.high,index)
            elif current.close < vwap and fast < slow and reference-current.close >= source.IMPULSE_ATR*atr:
                leg = source._Leg('bearish',current.low,index)
    return None


def update(state,today,*,ticker,now,scope):
    if not scope.startswith('research_worker:'):
        raise ValueError('Two-leg expansion is restricted to the research worker')
    cutoff = pd.Timestamp(now)
    cutoff = cutoff.tz_localize('America/New_York') if cutoff.tzinfo is None else cutoff.tz_convert('America/New_York')
    prices = pd.DataFrame(today)
    if prices.empty or not {'time','open','high','low','close'}.issubset(prices.columns):
        return None,'waiting_for_completed_1m_bars'
    times = pd.to_datetime(prices['time'])
    times = times.dt.tz_localize('America/New_York') if times.dt.tz is None else times.dt.tz_convert('America/New_York')
    prices = prices.assign(time=times).loc[times.dt.date == cutoff.date()]
    bars = source._completed_bars(prices,cutoff)
    if any(not all(math.isfinite(n) for n in (b.open,b.high,b.low,b.close,b.volume)) or
           not (0<b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high and b.volume>=0) for b in bars):
        return None,'invalid_candles'
    signal = latest_candidate(bars)
    if signal is None:
        return None,'waiting_for_impulse_pullback_reclaim'
    visible = signal.trigger_bar+pd.Timedelta(minutes=1)
    if not visible <= cutoff < visible+pd.Timedelta(minutes=1):
        return None,'stale_reclaim'
    key = (scope,ticker.strip().upper())
    if state.get(key) == signal.trigger_bar:
        return None,'already_observed_bar'
    from config.strategy_catalog import REVIEWED_STRATEGIES
    signal.meta.update(observation_only=True,research_emission_policy=POLICY,
        strategy_version=evidence_version(STRATEGY_ID,REVIEWED_STRATEGIES[STRATEGY_ID].version),
        implementation='trading.two_leg_research')
    state[key] = signal.trigger_bar
    return signal,'completed_1m_reclaim'
