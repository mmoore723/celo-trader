"""Paper-execution bridge for the reviewed TSLA two-leg trend pullback.

This is the production copy of the paid-data rule, deliberately kept separate
from the research package because research files are not deployed.  It uses
only *completed* one-minute regular-session candles:

* after the 09:45 reference, price, VWAP and EMA(9/20) establish a one-ATR
  impulse;
* price makes a controlled 0.25--1.25 ATR pullback to EMA(9) without closing
  through VWAP; and
* a completed one-minute candle reclaims the pullback's prior high/low and
  confirms the move with same-direction momentum, engulfing, or rejection.

The entry loop then selects the same reviewed near-money option and records
the next-minute executable ask.  The 90-minute same-contract bid exit is
handled by ``v2_orb_paper_exit``.  No incomplete candle is ever a signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import MutableMapping

import pandas as pd

from strategies.base import Signal
from strategies.price_action_context import PriceActionContext, describe_price_action


STRATEGY_ID = "V2_TSLA_TWO_LEG_TREND_PULLBACK"
TICKER = "TSLA"
REFERENCE_TIME = time(9, 45)
ENTRY_START = time(10, 0)
ENTRY_END = time(11, 30)
FAST_EMA = 9
SLOW_EMA = 20
ATR_BARS = 14
IMPULSE_ATR = 1.0
PULLBACK_MIN_ATR = 0.25
PULLBACK_MAX_ATR = 1.25
PULLBACK_LIMIT_BARS = 12
REWARD_RISK = 2.0


@dataclass(frozen=True)
class _Bar:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    rvol: float


@dataclass
class _Leg:
    direction: str
    impulse_extreme: float
    impulse_index: int
    pullback_extreme: float | None = None
    pullback_prior_high: float | None = None
    pullback_prior_low: float | None = None


def _completed_bars(today: pd.DataFrame, now: datetime) -> tuple[_Bar, ...]:
    """Return deduplicated completed regular-session one-minute bars only."""
    required = {"time", "open", "high", "low", "close"}
    if today.empty or not required.issubset(today.columns):
        return ()
    rows = today.copy()
    rows["time"] = pd.to_datetime(rows["time"])
    rows = rows.sort_values("time").drop_duplicates("time", keep="last")
    cutoff = pd.Timestamp(now).floor("min")
    source_tz = getattr(rows["time"].dt, "tz", None)
    if source_tz is None and cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    elif source_tz is not None and cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(source_tz)
    elif source_tz is not None:
        cutoff = cutoff.tz_convert(source_tz)
    rows = rows.loc[(rows["time"] < cutoff) & (rows["time"].dt.time >= time(9, 30)) & (rows["time"].dt.time <= time(15, 59))]
    return tuple(
        _Bar(
            timestamp=pd.Timestamp(row.time), open=float(row.open), high=float(row.high),
            low=float(row.low), close=float(row.close), volume=float(getattr(row, "volume", 0.0) or 0.0),
            rvol=float(getattr(row, "rvol", 0.0) or 0.0),
        )
        for row in rows.itertuples(index=False)
    )


def _ema(values: list[float], length: int) -> float:
    value = values[0]
    alpha = 2.0 / (length + 1.0)
    for item in values[1:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _atr(bars: list[_Bar], length: int) -> float:
    relevant = bars[-(length + 1):]
    ranges = [
        max(bar.high - bar.low, abs(bar.high - prior.close), abs(bar.low - prior.close))
        for prior, bar in zip(relevant, relevant[1:])
    ]
    return sum(ranges) / len(ranges) if ranges else 0.0


def _vwap(bars: list[_Bar]) -> float:
    price_volume = volume = 0.0
    for bar in bars:
        price_volume += ((bar.high + bar.low + bar.close) / 3.0) * max(bar.volume, 1.0)
        volume += max(bar.volume, 1.0)
    return price_volume / volume if volume else 0.0


def _reference_close(bars: list[_Bar]) -> float | None:
    for bar in bars:
        if bar.timestamp.time() == REFERENCE_TIME:
            return bar.close
    return None


def _has_directional_confirmation(context: PriceActionContext, direction: str) -> bool:
    """Return the paid-study candle confirmation for the completed reclaim.

    The context contains only bars at or before the reclaim bar.  Keeping this
    predicate here makes the production decision auditable and prevents a
    later candle from rescuing a weak reclaim.
    """
    if direction == "bullish":
        return context.momentum_long or context.bullish_engulfing or context.bullish_rejection
    if direction == "bearish":
        return context.momentum_short or context.bearish_engulfing or context.bearish_rejection
    raise ValueError(f"unsupported direction: {direction}")


def _signal_at_latest_bar(bars: tuple[_Bar, ...]) -> Signal | None:
    """Replay the small state machine and only return a current-minute signal.

    Replaying at most one session is cheap and, unlike an incremental cache,
    handles a bot restart in the middle of a valid setup without changing the
    rule.  The state transitions mirror the paid research strategy exactly.
    """
    today = list(bars)
    if not today:
        return None
    reference = _reference_close(today)
    leg: _Leg | None = None
    latest_signal: Signal | None = None
    minimum = max(SLOW_EMA, ATR_BARS + 1)
    for index, current in enumerate(today):
        clock = current.timestamp.time()
        if not (ENTRY_START <= clock <= ENTRY_END) or index + 1 < minimum or reference is None:
            continue
        history = today[:index + 1]
        closes = [bar.close for bar in history[-SLOW_EMA:]]
        fast = _ema(closes[-FAST_EMA:], FAST_EMA)
        slow = _ema(closes, SLOW_EMA)
        atr = _atr(history, ATR_BARS)
        vwap = _vwap(history)
        if atr <= 0:
            continue
        had_leg = leg is not None
        if leg is not None:
            elapsed = index - leg.impulse_index
            if elapsed > PULLBACK_LIMIT_BARS:
                leg = None
            else:
                previous = today[index - 1]
                if leg.direction == "bullish":
                    leg.impulse_extreme = max(leg.impulse_extreme, current.high)
                    retrace = leg.impulse_extreme - current.low
                    if current.close <= vwap or fast <= slow or retrace > PULLBACK_MAX_ATR * atr:
                        leg = None
                    elif leg.pullback_extreme is None:
                        if retrace >= PULLBACK_MIN_ATR * atr and current.low <= fast:
                            leg.pullback_extreme = current.low
                            leg.pullback_prior_high = previous.high
                    else:
                        leg.pullback_extreme = min(leg.pullback_extreme, current.low)
                        if current.close > previous.high and current.close > fast:
                            context = describe_price_action(
                                history, atr=atr, fast_ema=fast, slow_ema=slow, vwap=vwap,
                            )
                            if not _has_directional_confirmation(context, "bullish"):
                                # The reviewed study permits one setup per
                                # session.  Reject this completed reclaim for
                                # the day instead of searching forward after
                                # seeing its outcome.
                                leg = None
                                return None
                            stop = min(leg.pullback_extreme, current.close - atr)
                            risk = current.close - stop
                            if risk > 0:
                                latest_signal = Signal(
                                    confidence=0.80, strategy_id=STRATEGY_ID, direction="bullish", rvol=current.rvol,
                                    trigger_bar=current.timestamp,
                                    meta={
                                        **context.features(),
                                        "v2_hypothesis": "two_leg_impulse_vwap_hold_pullback_1m_reclaim",
                                        "validated_entry_rule": "after_0945_vwap_ema_aligned_1atr_impulse_pullback_fast_ema_then_directionally_confirmed_completed_1m_reclaim",
                                        "entry_timing": "completed_1m_reclaim_then_next_1m_option_ask",
                                        "directional_confirmation": True,
                                        "reference_945": round(reference, 6), "vwap": round(vwap, 6),
                                        "fast_ema": round(fast, 6), "slow_ema": round(slow, 6), "atr": round(atr, 6),
                                        "impulse_extreme": round(leg.impulse_extreme, 6),
                                        "pullback_low": round(leg.pullback_extreme, 6),
                                        "reclaim_level": round(previous.high, 6), "v2_entry_reference": round(current.close, 6),
                                        "v2_stop": round(stop, 6), "v2_target": round(current.close + REWARD_RISK * risk, 6),
                                        "pullback_min_atr": PULLBACK_MIN_ATR, "pullback_max_atr": PULLBACK_MAX_ATR,
                                    },
                                )
                                leg = None
                                # The study allows one setup per session. If
                                # this was a historical reclaim before a bot
                                # restart, do not manufacture a second later
                                # entry; only the newest completed minute may
                                # be returned to the live entry loop.
                                return latest_signal if index == len(today) - 1 else None
                else:
                    leg.impulse_extreme = min(leg.impulse_extreme, current.low)
                    retrace = current.high - leg.impulse_extreme
                    if current.close >= vwap or fast >= slow or retrace > PULLBACK_MAX_ATR * atr:
                        leg = None
                    elif leg.pullback_extreme is None:
                        if retrace >= PULLBACK_MIN_ATR * atr and current.high >= fast:
                            leg.pullback_extreme = current.high
                            leg.pullback_prior_low = previous.low
                    else:
                        leg.pullback_extreme = max(leg.pullback_extreme, current.high)
                        if current.close < previous.low and current.close < fast:
                            context = describe_price_action(
                                history, atr=atr, fast_ema=fast, slow_ema=slow, vwap=vwap,
                            )
                            if not _has_directional_confirmation(context, "bearish"):
                                leg = None
                                return None
                            stop = max(leg.pullback_extreme, current.close + atr)
                            risk = stop - current.close
                            if risk > 0:
                                latest_signal = Signal(
                                    confidence=0.80, strategy_id=STRATEGY_ID, direction="bearish", rvol=current.rvol,
                                    trigger_bar=current.timestamp,
                                    meta={
                                        **context.features(),
                                        "v2_hypothesis": "two_leg_impulse_vwap_hold_pullback_1m_reclaim",
                                        "validated_entry_rule": "after_0945_vwap_ema_aligned_1atr_impulse_pullback_fast_ema_then_directionally_confirmed_completed_1m_reclaim",
                                        "entry_timing": "completed_1m_reclaim_then_next_1m_option_ask",
                                        "directional_confirmation": True,
                                        "reference_945": round(reference, 6), "vwap": round(vwap, 6),
                                        "fast_ema": round(fast, 6), "slow_ema": round(slow, 6), "atr": round(atr, 6),
                                        "impulse_extreme": round(leg.impulse_extreme, 6),
                                        "pullback_high": round(leg.pullback_extreme, 6),
                                        "reclaim_level": round(previous.low, 6), "v2_entry_reference": round(current.close, 6),
                                        "v2_stop": round(stop, 6), "v2_target": round(current.close - REWARD_RISK * risk, 6),
                                        "pullback_min_atr": PULLBACK_MIN_ATR, "pullback_max_atr": PULLBACK_MAX_ATR,
                                    },
                                )
                                leg = None
                                return latest_signal if index == len(today) - 1 else None
        # An invalidated active leg cannot be reinterpreted as a new opposite
        # impulse on that same candle; a later completed candle may start one.
        if leg is None and not had_leg:
            if current.close > vwap and fast > slow and current.close - reference >= IMPULSE_ATR * atr:
                leg = _Leg("bullish", current.high, index)
            elif current.close < vwap and fast < slow and reference - current.close >= IMPULSE_ATR * atr:
                leg = _Leg("bearish", current.low, index)
    if latest_signal is None or latest_signal.trigger_bar != today[-1].timestamp:
        return None
    return latest_signal


def update_two_leg_trend_pullback(
    state: MutableMapping[str, object], today: pd.DataFrame, *, ticker: str, now: datetime,
) -> tuple[Signal | None, str]:
    """Return one reviewed setup per TSLA session or an explicit wait status."""
    if ticker.strip().upper() != TICKER:
        return None, "not_applicable"
    bars = _completed_bars(today, now)
    if not bars:
        return None, "waiting_for_completed_1m_bars"
    key = f"{TICKER}:{bars[-1].timestamp.date().isoformat()}"
    if state.get("key") != key:
        state.clear()
        state["key"] = key
    if state.get("emitted"):
        return None, "already_emitted"
    if _reference_close(list(bars)) is None:
        return None, "waiting_for_0945_reference"
    if bars[-1].timestamp.time() > ENTRY_END:
        return None, "entry_window_expired"
    signal = _signal_at_latest_bar(bars)
    if signal is None:
        return None, "waiting_for_impulse_pullback_reclaim"
    state["emitted"] = True
    return signal, "completed_1m_reclaim"
