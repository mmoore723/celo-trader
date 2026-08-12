"""Small, causal technical-indicator helpers for research filters.

These indicators deliberately operate only on completed bars supplied by a
strategy.  They are confirmation context, not a new buy/sell strategy.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from research.engine.models import Bar, Side, Signal
from research.engine.strategy import Strategy


def ema(values: list[float], length: int) -> float:
    """Return the causal EMA over the full supplied chronological series."""
    if length < 1 or not values:
        raise ValueError("EMA needs a positive length and at least one value")
    value = values[0]
    alpha = 2.0 / (length + 1.0)
    for item in values[1:]:
        value = item * alpha + value * (1.0 - alpha)
    return value


def rsi(values: list[float], length: int = 14) -> float | None:
    """Wilder RSI for a completed close series, returning None until ready."""
    if length < 2:
        raise ValueError("RSI length must be at least two")
    if len(values) < length + 1:
        return None
    changes = [right - left for left, right in zip(values, values[1:])]
    # Wilder's original smoothing: seed from the first completed 14 changes,
    # then carry that state forward one completed candle at a time.
    gains = sum(max(change, 0.0) for change in changes[:length]) / length
    losses = sum(max(-change, 0.0) for change in changes[:length]) / length
    for change in changes[length:]:
        gains = (gains * (length - 1) + max(change, 0.0)) / length
        losses = (losses * (length - 1) + max(-change, 0.0)) / length
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    relative_strength = gains / losses
    return 100.0 - (100.0 / (1.0 + relative_strength))


def macd_histogram(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9,
) -> float | None:
    """Return the current MACD histogram from completed closes only.

    The signal line is calculated from all causal MACD observations that can
    be formed from the provided history.  Nothing after the current candle is
    read.
    """
    if not (1 < fast < slow and signal > 1):
        raise ValueError("MACD requires 1 < fast < slow and signal > 1")
    if len(values) < slow + signal - 1:
        return None
    # Both EMAs retain all prior completed observations.  Truncating the
    # series to the last 12/26 bars silently turns MACD into a different,
    # noisy indicator.
    fast_value, slow_value = values[0], values[0]
    fast_alpha, slow_alpha = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    macd_values: list[float] = []
    for index, value in enumerate(values[1:], start=1):
        fast_value = value * fast_alpha + fast_value * (1.0 - fast_alpha)
        slow_value = value * slow_alpha + slow_value * (1.0 - slow_alpha)
        if index >= slow - 1:
            macd_values.append(fast_value - slow_value)
    if len(macd_values) < signal:
        return None
    line = macd_values[-1]
    signal_line = ema(macd_values[-signal:], signal)
    return line - signal_line


def confirmed_signals(
    bars: Iterable[Bar], strategy: Strategy, *, indicator_history: Iterable[Bar] = (),
    require_rsi: bool = False, require_macd: bool = False,
) -> tuple[Signal, ...]:
    """Keep only base-strategy signals whose momentum agrees with direction.

    Longs require RSI at/above 50 and/or positive MACD histogram; shorts use
    the exact inverse.  The neutral 50 RSI rule intentionally avoids a
    counter-trend "overbought/oversold" interpretation.
    """
    # The entry strategy receives only the current session.  Indicators may
    # use prior completed sessions so a 26/9 MACD is genuinely ready at the
    # open rather than being accidentally unavailable until midday.
    history: list[Bar] = []
    indicator_bars = list(indicator_history)
    # ``bars`` may be a generator; materialize it once before checking the
    # first timestamp so no session candle is consumed by validation.
    current_bars = tuple(bars)
    if not current_bars:
        return ()
    if indicator_bars and indicator_bars[-1].timestamp >= current_bars[0].timestamp:
        raise ValueError("indicator history must end before the tested session")
    output: list[Signal] = []
    for bar in current_bars:
        history.append(bar)
        base = strategy.evaluate(history)
        if base is None:
            continue
        closes = [item.close for item in (*indicator_bars, *history)]
        current_rsi = rsi(closes) if require_rsi else None
        current_macd = macd_histogram(closes) if require_macd else None
        if require_rsi and current_rsi is None:
            continue
        if require_macd and current_macd is None:
            continue
        rsi_ok = (not require_rsi or
                  (current_rsi >= 50.0 if base.side is Side.LONG else current_rsi <= 50.0))
        macd_ok = (not require_macd or
                   (current_macd > 0.0 if base.side is Side.LONG else current_macd < 0.0))
        if rsi_ok and macd_ok:
            features = dict(base.features)
            if current_rsi is not None:
                features["rsi_14"] = round(current_rsi, 4)
            if current_macd is not None:
                features["macd_histogram_12_26_9"] = round(current_macd, 6)
            output.append(replace(base, features=features))
    return tuple(output)
