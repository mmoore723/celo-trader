"""Reviewed SPY afternoon Fair Value Gap adapter.

This is intentionally *not* the legacy ``FVG`` strategy.  It reproduces the
predeclared paid-option study: completed five-minute SPY bars, the first
retest of a three-bar imbalance, EMA/VWAP alignment, and a 13:30--15:00 ET
signal window.  A signal becomes eligible on the following one-minute bar.
"""
from __future__ import annotations

from datetime import time
from typing import Sequence

import pandas as pd

from strategies.base import Signal
from strategies.market_structure import Bar, _atr, _ema
from strategies.price_action_context import describe_price_action
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars


STRATEGY_ID = "V2_SPY_AFTERNOON_FVG"
VALIDATED_TICKERS = frozenset({"SPY"})
_emitted_trigger_by_session: set[tuple[str, str, str, str, float, float]] = set()

_FAST_EMA = 8
_SLOW_EMA = 20
_ATR_BARS = 14
_SCAN_BARS = 30
_MIN_GAP_ATR = 0.5
_START = time(13, 30)
_END = time(15, 0)


def _session_vwap(bars: Sequence[Bar]) -> float:
    price_volume = volume = 0.0
    for bar in bars:
        bar_volume = max(float(bar.volume), 1.0)
        price_volume += ((bar.high + bar.low + bar.close) / 3.0) * bar_volume
        volume += bar_volume
    return price_volume / volume if volume else 0.0


def _signal_from_completed_bars(bars: Sequence[Bar]) -> Signal | None:
    """Return the exact first-retest FVG premise used by the paid study."""
    if not bars:
        return None
    current_date = bars[-1].timestamp.date()
    today = tuple(bar for bar in bars if bar.timestamp.date() == current_date)
    minimum = max(_SLOW_EMA, _ATR_BARS + 1, 6)
    if len(today) < minimum:
        return None
    current = today[-1]
    if not (_START <= current.timestamp.time() < _END):
        return None
    atr = _atr(today, _ATR_BARS)
    if atr <= 0:
        return None
    closes = [bar.close for bar in today[-_SLOW_EMA:]]
    fast = _ema(closes[-_FAST_EMA:], _FAST_EMA)
    slow = _ema(closes, _SLOW_EMA)
    vwap = _session_vwap(today)
    price_action = describe_price_action(
        today, atr=atr, fast_ema=fast, slow_ema=slow, vwap=vwap,
    ).features()
    newest = len(today) - 3
    oldest = max(1, newest - _SCAN_BARS + 1)

    for middle in range(newest, oldest - 1, -1):
        before, after = today[middle - 1], today[middle + 1]
        intervening = today[middle + 2:-1]
        if before.high < after.low:
            lower, upper = before.high, after.low
            if upper - lower < _MIN_GAP_ATR * atr or not (fast > slow and current.close > vwap):
                continue
            if any(bar.low <= upper and bar.high >= lower for bar in intervening):
                continue
            midpoint = (lower + upper) / 2.0
            if current.low <= upper and current.high >= lower and current.close > midpoint:
                stop = min(current.low, current.close - atr)
                risk = current.close - stop
                if risk > 0:
                    return Signal(
                        strategy_id=STRATEGY_ID, direction="bullish", confidence=0.80,
                        rvol=0.0, trigger_bar=pd.Timestamp(current.timestamp),
                        meta={
                            **price_action,
                            "v2_hypothesis": "spy_afternoon_fvg_first_retest_5m",
                            "reviewed_paid_quote_rule": True,
                            "entry_timing": "completed_5m_signal_then_next_1m_entry",
                            "gap_lower": round(lower, 6), "gap_upper": round(upper, 6),
                            "atr": round(atr, 6), "vwap": round(vwap, 6),
                            "ema_fast": round(fast, 6), "ema_slow": round(slow, 6),
                            "trigger": "upward_gap_retest", "v2_entry_reference": current.close,
                            "v2_stop": stop, "v2_target": current.close + 2.0 * risk,
                            "entry_bar_low": stop, "entry_bar_high": None,
                        },
                    )
        elif before.low > after.high:
            lower, upper = after.high, before.low
            if upper - lower < _MIN_GAP_ATR * atr or not (fast < slow and current.close < vwap):
                continue
            if any(bar.low <= upper and bar.high >= lower for bar in intervening):
                continue
            midpoint = (lower + upper) / 2.0
            if current.low <= upper and current.high >= lower and current.close < midpoint:
                stop = max(current.high, current.close + atr)
                risk = stop - current.close
                if risk > 0:
                    return Signal(
                        strategy_id=STRATEGY_ID, direction="bearish", confidence=0.80,
                        rvol=0.0, trigger_bar=pd.Timestamp(current.timestamp),
                        meta={
                            **price_action,
                            "v2_hypothesis": "spy_afternoon_fvg_first_retest_5m",
                            "reviewed_paid_quote_rule": True,
                            "entry_timing": "completed_5m_signal_then_next_1m_entry",
                            "gap_lower": round(lower, 6), "gap_upper": round(upper, 6),
                            "atr": round(atr, 6), "vwap": round(vwap, 6),
                            "ema_fast": round(fast, 6), "ema_slow": round(slow, 6),
                            "trigger": "downward_gap_retest", "v2_entry_reference": current.close,
                            "v2_stop": stop, "v2_target": current.close - 2.0 * risk,
                            "entry_bar_low": None, "entry_bar_high": stop,
                        },
                    )
    return None


def evaluate(
    today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None,
) -> Signal | None:
    ticker = ticker.strip().upper()
    if ticker not in VALIDATED_TICKERS:
        return None
    candidate = _signal_from_completed_bars(_complete_five_minute_bars(today))
    if candidate is None:
        return None
    lower = float(candidate.meta["gap_lower"])
    upper = float(candidate.meta["gap_upper"])
    from strategies.spy_trend_continuation_v2 import _execution_scope
    key = (
        _execution_scope(execution_scope), ticker,
        candidate.trigger_bar.date().isoformat(), candidate.direction, lower, upper,
    )
    if key in _emitted_trigger_by_session:
        return None
    _emitted_trigger_by_session.add(key)
    latest = today.iloc[-1]
    return Signal(
        strategy_id=candidate.strategy_id, direction=candidate.direction,
        confidence=candidate.confidence, rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=candidate.trigger_bar, meta=candidate.meta,
    )
