"""Reviewed SPY afternoon-reversal adapter.

This is deliberately separate from the old generic ``AFT_REV`` strategy.
It reproduces the paid-option study that passed its untouched later dates:
SPY only, long only, a completed five-minute higher-low / break-of-structure
setup from 1:00--2:00 PM ET, with the following one-minute bar eligible to
enter.  The reviewed paper exit is the same contract's bid 30 minutes later.
"""
from __future__ import annotations

from datetime import time
from typing import Sequence

import pandas as pd

from strategies.base import Signal
from strategies.market_structure import Bar, _atr
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars


STRATEGY_ID = "V2_SPY_AFTERNOON_REVERSAL"
VALIDATED_TICKERS = frozenset({"SPY"})
_emitted_trigger_by_session: dict[tuple[str, str], pd.Timestamp] = {}

_PIVOT_LOOKBACK = 3
_ATR_BARS = 14
_MIN_MORNING_SELLOFF_PCT = 0.005
_START = time(13, 0)
_END = time(14, 0)


def _session_vwap(bars: Sequence[Bar]) -> float:
    price_volume = volume = 0.0
    for bar in bars:
        bar_volume = max(float(bar.volume), 1.0)
        price_volume += ((bar.high + bar.low + bar.close) / 3.0) * bar_volume
        volume += bar_volume
    return price_volume / volume if volume else 0.0


def _confirmed_swings(
    bars: Sequence[Bar], lookback: int = _PIVOT_LOOKBACK,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Return pivots only after bars on both sides have completed.

    This is the same confirmation rule used in the paid research.  It avoids
    pretending that an in-progress low or high is a finished swing.
    """
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for index in range(lookback, len(bars) - lookback):
        window = bars[index - lookback:index + lookback + 1]
        if bars[index].high == max(bar.high for bar in window):
            highs.append((index, bars[index].high))
        if bars[index].low == min(bar.low for bar in window):
            lows.append((index, bars[index].low))
    return highs, lows


def _signal_from_completed_bars(bars: Sequence[Bar]) -> Signal | None:
    """Return the exact long-only premise selected by the paid study."""
    if not bars:
        return None
    current_date = bars[-1].timestamp.date()
    today = tuple(bar for bar in bars if bar.timestamp.date() == current_date)
    minimum = max(_ATR_BARS + 1, 2 * _PIVOT_LOOKBACK + 5)
    if len(today) < minimum:
        return None
    current = today[-1]
    if not (_START <= current.timestamp.time() < _END):
        return None

    highs, lows = _confirmed_swings(today)
    if len(highs) < 2 or len(lows) < 2:
        return None
    atr = _atr(today, _ATR_BARS)
    if atr <= 0:
        return None
    vwap = _session_vwap(today)
    opening_price = today[0].open
    session_low = min(bar.low for bar in today)
    last_high, _prior_high = highs[-1], highs[-2]
    last_low, prior_low = lows[-1], lows[-2]
    morning_selloff = (opening_price - session_low) / opening_price >= _MIN_MORNING_SELLOFF_PCT
    if not (
        morning_selloff
        and last_low[1] > prior_low[1]
        and current.close > last_high[1]
        and current.close > vwap
    ):
        return None

    stop = min(last_low[1], current.close - atr)
    risk = current.close - stop
    if risk <= 0:
        return None
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish",
        confidence=0.80,
        rvol=0.0,
        trigger_bar=pd.Timestamp(current.timestamp),
        meta={
            "v2_hypothesis": "spy_afternoon_reversal_5m_long",
            "reviewed_paid_quote_rule": True,
            "entry_timing": "completed_5m_signal_then_next_1m_entry",
            "trigger": "morning_selloff_higher_low_bos",
            "atr": round(atr, 6),
            "vwap": round(vwap, 6),
            "morning_low": round(session_low, 6),
            "confirmed_swing_high": round(last_high[1], 6),
            "confirmed_higher_low": round(last_low[1], 6),
            "v2_entry_reference": current.close,
            "v2_stop": stop,
            "v2_target": current.close + 2.0 * risk,
            "entry_bar_low": stop,
            "entry_bar_high": None,
        },
    )


def evaluate(today: pd.DataFrame, ticker: str = "") -> Signal | None:
    """Adapt live one-minute data while keeping the paid-study timing intact."""
    ticker = ticker.strip().upper()
    if ticker not in VALIDATED_TICKERS:
        return None
    candidate = _signal_from_completed_bars(_complete_five_minute_bars(today))
    if candidate is None:
        return None
    key = (ticker, candidate.trigger_bar.date().isoformat())
    if _emitted_trigger_by_session.get(key) == candidate.trigger_bar:
        return None
    _emitted_trigger_by_session[key] = candidate.trigger_bar
    latest = today.iloc[-1]
    return Signal(
        strategy_id=candidate.strategy_id,
        direction=candidate.direction,
        confidence=candidate.confidence,
        rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=candidate.trigger_bar,
        meta=candidate.meta,
    )
