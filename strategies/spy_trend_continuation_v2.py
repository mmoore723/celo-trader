"""Reviewed SPY Trend Continuation adapter.

This is intentionally a separate identity from the earlier TSLA experiment.
It rebuilds complete five-minute candles from live one-minute bars, matching
the paid SPY study: a signal at a completed five-minute close is eligible on
the following minute, and its reviewed one-position exit is 30 minutes after
entry.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from strategies.market_structure import Bar, Side, TrendContinuation, TrendContinuationConfig, resample_regular_session
from strategies.base import Signal


STRATEGY_ID = "V2_SPY_TREND_CONT"
VALIDATED_TICKERS = frozenset({"SPY"})
_emitted_trigger_by_session: dict[tuple[str, str, str], pd.Timestamp] = {}
# A breakout may keep printing higher completed candles after its first
# trigger.  They remain one breakout attempt until price actually returns
# through the broken level.  This mirrors the paid-data research definition
# and avoids stacking entries into one continuous move.
_active_breakout_by_session: dict[tuple[str, str, str], tuple[Side, float]] = {}


def _execution_scope(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    from auth.context import get_current_user_id
    return get_current_user_id()


def _complete_five_minute_bars(
    today: pd.DataFrame, now: object | None = None,
) -> tuple[Bar, ...]:
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(today.columns):
        return ()
    rows = today.sort_values("time").drop_duplicates("time")
    times = pd.to_datetime(rows["time"])
    # Live bar endpoints can include the currently forming minute.  The paid
    # study only used completed bars, so remove that minute before aggregation.
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    cutoff = cutoff.floor("min")
    rows = rows.loc[times < cutoff]
    one_minute = tuple(
        Bar(
            pd.Timestamp(row.time).to_pydatetime(), float(row.open),
            float(row.high), float(row.low), float(row.close),
            float(getattr(row, "volume", 0.0)),
        )
        for row in rows.itertuples(index=False)
    )
    # The resampler rejects an unfinished 5-minute bucket.  This protects the
    # live adapter from treating a forming bar as the closed bar used in study.
    return resample_regular_session(one_minute, source_minutes=1, target_minutes=5)


def evaluate(
    today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None,
) -> Signal | None:
    if ticker.strip().upper() not in VALIDATED_TICKERS:
        return None
    bars = _complete_five_minute_bars(today)
    config = TrendContinuationConfig()
    minimum = max(config.slow_ema, config.atr_bars + 1, config.breakout_bars + 1)
    if len(bars) < minimum:
        return None
    # The strategy must re-arm as soon as the completed structure candle
    # closes back through its old breakout level, even if that reset candle is
    # not itself a new TrendContinuation signal.  Keying from the current
    # session avoids depending on a future candidate merely to clear state.
    session_date = pd.Timestamp(today.iloc[-1]["time"]).date().isoformat()
    session_key = (_execution_scope(execution_scope), ticker.strip().upper(), session_date)
    active = _active_breakout_by_session.get(session_key)
    if active is not None:
        active_side, broken_level = active
        reset = ((active_side is Side.LONG and bars[-1].close <= broken_level)
                 or (active_side is Side.SHORT and bars[-1].close >= broken_level))
        if reset:
            _active_breakout_by_session.pop(session_key, None)
            active = None
    candidate = TrendContinuation(config).evaluate(bars)
    if candidate is None:
        return None
    trigger = pd.Timestamp(candidate.timestamp)
    # The live loop runs every minute whereas this premise decides on a closed
    # five-minute candle.  One candle earns one next-minute attempt, exactly as
    # the paid markout used; it must not be re-emitted on the following minutes.
    if _emitted_trigger_by_session.get(session_key) == trigger:
        return None
    # Do not emit another entry while the earlier directional breakout remains
    # intact.  A reset through its broken level above re-arms the strategy.
    if active is not None and active[0] is candidate.side:
        return None
    _emitted_trigger_by_session[session_key] = trigger
    broken_level = candidate.features.get("prior_high" if candidate.side is Side.LONG else "prior_low")
    if broken_level is None:
        return None
    _active_breakout_by_session[session_key] = (candidate.side, float(broken_level))
    latest = today.iloc[-1]
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish" if candidate.side.value == "long" else "bearish",
        confidence=0.80,
        rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=pd.Timestamp(candidate.timestamp),
        meta={
            **candidate.features,
            "v2_hypothesis": "spy_trend_continuation_5m",
            "reviewed_paid_quote_rule": True,
            "entry_timing": "completed_5m_signal_then_next_1m_entry",
            "v2_entry_reference": float(candidate.entry_reference),
            "v2_stop": float(candidate.stop),
            "v2_target": float(candidate.target),
            "entry_bar_low": float(candidate.stop) if candidate.side.value == "long" else None,
            "entry_bar_high": float(candidate.stop) if candidate.side.value == "short" else None,
        },
    )
