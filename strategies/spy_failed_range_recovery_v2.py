"""Reviewed SPY failed-opening-range recovery adapter.

The paid study observes completed one-minute bars.  A completed close must
first break the 09:30--09:44 opening range, then an opposite-colour candle
must close back inside while there is still room to session VWAP.  Production
recomputes that state from the completed session on every tick so restarts do
not change the signal, and the router may attempt the signal only once.
"""
from __future__ import annotations

from config.engine_parameters import parameter
from config.strategy_inputs import opening_end

from datetime import time

import pandas as pd

from strategies.base import Signal
from strategies.market_structure import Bar, Side, _atr, _ema, _opening_range
from strategies.price_action_context import describe_price_action
from strategies.spy_trend_continuation_v2 import _execution_scope


STRATEGY_ID = "V2_FAILED_OR_BREAK_VWAP_REVERSION"
VALIDATED_TICKERS = frozenset({"SPY"})
BREAKOUT_DEADLINE = time(11, 0)
FAILURE_DEADLINE = time(12, 0)
MINIMUM_EXCURSION_RANGE = 0.05
MINIMUM_VWAP_ROOM_RANGE = 0.05
STOP_BUFFER_RANGE = 0.10
_emitted_trigger_by_session: dict[tuple[str, str, str], pd.Timestamp] = {}


def _completed_one_minute_bars(today: pd.DataFrame, now: object | None = None) -> tuple[Bar, ...]:
    required = {"time", "open", "high", "low", "close"}
    if today.empty or not required.issubset(today.columns):
        return ()
    rows = today.sort_values("time").drop_duplicates("time")
    times = pd.to_datetime(rows["time"])
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    rows = rows.loc[times < cutoff.floor("min")]
    # The paid study and its exact production-parity proof use regular-session
    # bars only.  The live Alpaca frame can also contain sparse premarket and
    # postmarket observations; allowing those into session VWAP, ATR, or
    # price-action context makes production evaluate a different rule.
    clocks = pd.to_datetime(rows["time"]).dt.time
    rows = rows.loc[(clocks >= time(9, 30)) & (clocks < time(16, 0))]
    return tuple(
        Bar(
            pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
            float(row.low), float(row.close), float(getattr(row, "volume", 0.0)),
        )
        for row in rows.itertuples(index=False)
    )


def _session_vwap(bars: tuple[Bar, ...]) -> float:
    price_volume = volume = 0.0
    for bar in bars:
        weight = max(float(bar.volume), 1.0)
        price_volume += ((bar.high + bar.low + bar.close) / 3.0) * weight
        volume += weight
    return price_volume / volume


def _candidate_from_completed_bars(bars: tuple[Bar, ...]) -> tuple[Side, Bar, float, float, float, float] | None:
    """Return the first causal failed break, matching the selected paid rule."""
    from trading.diagnostics.entry_checks import record_checks, add_check
    opening = _opening_range(bars)
    if opening is None:
        add_check("Opening range", reason="Waiting for the complete opening range.", pending=True)
        return None
    range_high, range_low = opening
    width = range_high - range_low
    if width <= 0:
        return None
    breakout_side: Side | None = None
    breakout_bar: Bar | None = None
    for index, bar in enumerate(bars):
        record_checks([])
        add_check("Opening range", width > 0, f"Range ${range_low:.2f} to ${range_high:.2f}.")
        clock = bar.timestamp.time()
        if clock < opening_end():
            continue
        if breakout_side is None:
            if clock > parameter('breakout_deadline', BREAKOUT_DEADLINE):
                add_check("Break deadline", False, "No qualifying break before the configured deadline.")
                return None
            excursion = width * parameter('minimum_excursion_range', MINIMUM_EXCURSION_RANGE)
            if bar.close >= range_high + excursion:
                breakout_side, breakout_bar = Side.LONG, bar
            elif bar.close <= range_low - excursion:
                breakout_side, breakout_bar = Side.SHORT, bar
            add_check("Range break", True if breakout_side else None, f"Completed candle {bar.timestamp}; close ${bar.close:.2f}; required excursion ${excursion:.2f}.", pending=breakout_side is None)
            continue
        if clock > parameter('failure_deadline', FAILURE_DEADLINE):
            add_check("Recovery deadline", False, "The configured recovery deadline has passed.")
            return None
        assert breakout_bar is not None
        prefix = bars[: index + 1]
        vwap = bar.close + (_session_vwap(prefix)-bar.close)*parameter("vwap_target_fraction",1.)
        room = width * parameter('minimum_vwap_room_range', MINIMUM_VWAP_ROOM_RANGE)
        add_check("Range break", True, f"First break at {breakout_bar.timestamp}.")
        recovered = (bar.close <= range_high and bar.close < bar.open) if breakout_side is Side.LONG else (bar.close >= range_low and bar.close > bar.open)
        add_check("Recovery candle", recovered, f"Completed candle {bar.timestamp}: open ${bar.open:.2f}, close ${bar.close:.2f}. Must return inside the range in the opposite direction.")
        add_check("Room to VWAP", bar.close-vwap >= room if breakout_side is Side.LONG else vwap-bar.close >= room, f"VWAP ${vwap:.2f}; minimum room ${room:.2f}.")
        if breakout_side is Side.LONG and bar.close <= range_high and bar.close < bar.open:
            if bar.close - vwap >= room:
                stop = max(breakout_bar.high, bar.high) + width * parameter('stop_buffer_range', STOP_BUFFER_RANGE)
                return Side.SHORT, bar, stop, vwap, range_high, range_low
            return None
        if breakout_side is Side.SHORT and bar.close >= range_low and bar.close > bar.open:
            if vwap - bar.close >= room:
                stop = min(breakout_bar.low, bar.low) - width * parameter('stop_buffer_range', STOP_BUFFER_RANGE)
                return Side.LONG, bar, stop, vwap, range_high, range_low
            return None
    return None


def evaluate(
    today: pd.DataFrame,
    ticker: str = "",
    execution_scope: str | None = None,
    now: object | None = None,
) -> Signal | None:
    ticker = ticker.strip().upper()
    if ticker not in VALIDATED_TICKERS:
        return None
    from config.strategy_inputs import aggregate_entry_bars
    bars = aggregate_entry_bars(_completed_one_minute_bars(today, now=now),keep_opening=True)
    candidate = _candidate_from_completed_bars(bars)
    if candidate is None:
        return None
    side, trigger, stop, target, range_high, range_low = candidate
    trigger_time = pd.Timestamp(trigger.timestamp)
    # This paid rule enters on the minute immediately after the completed
    # failure candle.  Recomputing the first morning failure after a process
    # restart must not turn that expired setup into an afternoon (or next-day)
    # order.  Historical/research calls still work because they advance the
    # input frame one completed bar at a time.
    if trigger_time != pd.Timestamp(bars[-1].timestamp):
        from trading.diagnostics.entry_checks import add_check
        add_check("Fresh setup", False, f"The first recovery occurred at {trigger_time}; it is no longer the latest candle.")
        return None
    session_key = (_execution_scope(execution_scope), ticker, trigger.timestamp.date().isoformat())
    if _emitted_trigger_by_session.get(session_key) == trigger_time:
        return None
    _emitted_trigger_by_session[session_key] = trigger_time
    closes = [bar.close for bar in bars[-20:]]
    atr = _atr(bars, 14)
    price_action = (
        describe_price_action(
            bars,
            atr=atr,
            fast_ema=_ema(closes[-8:], 8),
            slow_ema=_ema(closes, 20),
            vwap=_session_vwap(bars),
        ).features()
        if atr > 0 else {}
    )
    latest = today.sort_values("time").iloc[-1]
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish" if side is Side.LONG else "bearish",
        confidence=0.80,
        rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=trigger_time,
        meta={
            **price_action,
            "trigger": "downward_opening_range_break_failed_back_inside"
            if side is Side.LONG else "upward_opening_range_break_failed_back_inside",
            "or_high": round(range_high, 6), "or_low": round(range_low, 6),
            "vwap": round(target, 6),
            "v2_entry_reference": float(trigger.close),
            "v2_stop": float(stop), "v2_target": float(target),
            "entry_bar_low": float(trigger.low) if side is Side.LONG else None,
            "entry_bar_high": float(trigger.high) if side is Side.SHORT else None,
            "entry_timing": "completed_1m_failure_then_next_1m_entry",
            "reviewed_paid_quote_rule": True,
            "reviewed_exit_minutes": 30,
        },
    )
