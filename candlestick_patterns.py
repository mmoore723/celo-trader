"""
candlestick_patterns.py — Rule-based candlestick rejection/continuation shapes.

Plain OHLC arithmetic, NOT machine learning. Same kind of body/wick-ratio
math already used elsewhere in this codebase (chan_break.py's wick
requirement, the momentum-dead exit's candle-body check) — just packaged
as reusable named patterns instead of one-off inline checks.

Used by strategies/vwap_pb.py (behind CANDLESTICK_FILTER_ENABLED, OFF by
default) to distinguish a genuine VWAP-touch rejection (hammer/shooting
star) from a touch that's actually a continuation candle in disguise.
See ab_test_candlestick_filter.py for the backtest comparison before this
is ever turned on live.
"""

from __future__ import annotations

from typing import Mapping

_EPS = 1e-9


def _parts(bar: Mapping) -> tuple[float, float, float, float]:
    """Extract (body, upper_wick, lower_wick, range) from an OHLC bar/Series."""
    o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    body  = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    rng   = max(h - l, _EPS)
    return body, upper, lower, rng


def is_hammer(bar: Mapping, min_wick_ratio: float = 2.0, max_upper_ratio: float = 0.5) -> bool:
    """
    Bullish rejection: long lower wick (buyers stepped in and rejected lower
    prices), small upper wick, body sits in the upper portion of the range.
    Classic signal that a dip/touch was defended, not just paused on the way
    down. Works on a doji-bodied bar too (body -> 0 is still a valid hammer
    if the lower wick dominates, i.e. a dragonfly doji).
    """
    body, upper, lower, rng = _parts(bar)
    _body_ref = max(body, rng * 0.05)   # floor so a true doji doesn't divide by ~0
    return (lower >= min_wick_ratio * _body_ref) and (upper <= _body_ref * max_upper_ratio)


def is_shooting_star(bar: Mapping, min_wick_ratio: float = 2.0, max_lower_ratio: float = 0.5) -> bool:
    """
    Bearish rejection: long upper wick (sellers stepped in and rejected
    higher prices), small lower wick, body sits in the lower portion of the
    range. Mirror of is_hammer().
    """
    body, upper, lower, rng = _parts(bar)
    _body_ref = max(body, rng * 0.05)
    return (upper >= min_wick_ratio * _body_ref) and (lower <= _body_ref * max_lower_ratio)
