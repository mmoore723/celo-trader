"""Causal, production-safe price-action context for reviewed strategies.

The module describes a setup; it does not approve or reject one.  Every value
uses completed bars at or before the signal bar so the same calculation can be
used by paid-data research and live paper execution without lookahead.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Protocol, Sequence


class OHLCBar(Protocol):
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PriceActionContext:
    candle_direction: str
    body_to_range: float
    close_location: float
    upper_wick_to_range: float
    lower_wick_to_range: float
    bullish_engulfing: bool
    bearish_engulfing: bool
    inside_bar: bool
    bullish_rejection: bool
    bearish_rejection: bool
    doji: bool
    long_legged_doji: bool
    hammer: bool
    inverted_hammer: bool
    shooting_star: bool
    hanging_man: bool
    bullish_harami: bool
    bearish_harami: bool
    morning_star: bool
    evening_star: bool
    three_white_soldiers: bool
    three_black_crows: bool
    bullish_marubozu: bool
    bearish_marubozu: bool
    bullish_failed_break: bool
    bearish_failed_break: bool
    consecutive_higher_lows: bool
    consecutive_lower_highs: bool
    momentum_long: bool
    momentum_short: bool
    nearest_support: float | None
    nearest_resistance: float | None
    support_distance_atr: float | None
    resistance_distance_atr: float | None
    close_to_fast_ema_atr: float | None
    close_to_slow_ema_atr: float | None
    close_to_vwap_atr: float | None

    def features(self, prefix: str = "pa_") -> dict[str, float | str | bool]:
        return {f"{prefix}{key}": value for key, value in asdict(self).items() if value is not None}


def _ratio(value: float, denominator: float) -> float:
    return value / denominator if denominator > 0 else 0.0


def _confirmed_pivots(bars: Sequence[OHLCBar], wing: int = 2) -> tuple[list[float], list[float]]:
    """Return pivots confirmed by ``wing`` later completed bars.

    The final ``wing`` bars can never be pivots because confirming them would
    require future data.  Equal highs/lows are deliberately not called pivots.
    """
    highs: list[float] = []
    lows: list[float] = []
    for index in range(wing, len(bars) - wing):
        window = bars[index - wing:index + wing + 1]
        current = bars[index]
        if current.high == max(bar.high for bar in window) and sum(bar.high == current.high for bar in window) == 1:
            highs.append(float(current.high))
        if current.low == min(bar.low for bar in window) and sum(bar.low == current.low for bar in window) == 1:
            lows.append(float(current.low))
    return highs, lows


def describe_price_action(
    bars: Sequence[OHLCBar], *, atr: float, fast_ema: float | None = None,
    slow_ema: float | None = None, vwap: float | None = None, pivot_wing: int = 2,
) -> PriceActionContext:
    """Describe the latest completed candle and already-confirmed structure."""
    if not bars:
        raise ValueError("at least one completed bar is required")
    if atr <= 0:
        raise ValueError("atr must be positive")
    if pivot_wing < 1:
        raise ValueError("pivot_wing must be positive")
    current = bars[-1]
    previous = bars[-2] if len(bars) > 1 else None
    third = bars[-3] if len(bars) > 2 else None
    span = max(float(current.high) - float(current.low), 0.0)
    body = abs(float(current.close) - float(current.open))
    upper = float(current.high) - max(float(current.open), float(current.close))
    lower = min(float(current.open), float(current.close)) - float(current.low)
    close_location = _ratio(float(current.close) - float(current.low), span)
    bullish = current.close > current.open
    bearish = current.close < current.open
    bullish_engulfing = bool(previous and bullish and previous.close < previous.open
                             and current.open <= previous.close and current.close >= previous.open)
    bearish_engulfing = bool(previous and bearish and previous.close > previous.open
                             and current.open >= previous.close and current.close <= previous.open)
    inside = bool(previous and current.high <= previous.high and current.low >= previous.low)
    body_ratio = _ratio(body, span)
    upper_ratio, lower_ratio = _ratio(upper, span), _ratio(lower, span)
    highs, lows = _confirmed_pivots(bars, pivot_wing)
    support = max((level for level in lows if level < current.close), default=None)
    resistance = min((level for level in highs if level > current.close), default=None)
    previous_span = max(float(previous.high) - float(previous.low), 0.0) if previous else 0.0
    previous_body = abs(float(previous.close) - float(previous.open)) if previous else 0.0
    doji = body_ratio <= 0.10
    long_legged_doji = doji and upper_ratio >= 0.35 and lower_ratio >= 0.35
    hammer_shape = lower_ratio >= 0.55 and upper_ratio <= 0.15 and body_ratio <= 0.40
    inverted_shape = upper_ratio >= 0.55 and lower_ratio <= 0.15 and body_ratio <= 0.40
    bullish_harami = bool(previous and previous.close < previous.open and bullish
                          and current.open >= previous.close and current.close <= previous.open
                          and body < previous_body)
    bearish_harami = bool(previous and previous.close > previous.open and bearish
                          and current.open <= previous.close and current.close >= previous.open
                          and body < previous_body)
    morning_star = bool(third and previous and third.close < third.open and bullish
                        and abs(previous.close - previous.open) <= previous_span * 0.30
                        and current.close > (third.open + third.close) / 2.0)
    evening_star = bool(third and previous and third.close > third.open and bearish
                        and abs(previous.close - previous.open) <= previous_span * 0.30
                        and current.close < (third.open + third.close) / 2.0)
    three_white = bool(third and previous and third.close > third.open and previous.close > previous.open and bullish
                       and third.close < previous.close < current.close
                       and third.low < previous.low < current.low)
    three_black = bool(third and previous and third.close < third.open and previous.close < previous.open and bearish
                       and third.close > previous.close > current.close
                       and third.high > previous.high > current.high)
    bullish_marubozu = bullish and body_ratio >= 0.85 and upper_ratio <= 0.08 and lower_ratio <= 0.08
    bearish_marubozu = bearish and body_ratio >= 0.85 and upper_ratio <= 0.08 and lower_ratio <= 0.08
    prior_highs = highs[:-1] if highs and highs[-1] == current.high else highs
    prior_lows = lows[:-1] if lows and lows[-1] == current.low else lows
    recent_resistance = min((level for level in prior_highs if level >= current.low), default=None)
    recent_support = max((level for level in prior_lows if level <= current.high), default=None)
    bullish_failed_break = bool(recent_support is not None and current.low < recent_support < current.close
                                and close_location >= 0.60)
    bearish_failed_break = bool(recent_resistance is not None and current.high > recent_resistance > current.close
                                and close_location <= 0.40)
    higher_lows = bool(third and previous and third.low < previous.low < current.low)
    lower_highs = bool(third and previous and third.high > previous.high > current.high)

    return PriceActionContext(
        candle_direction="bullish" if bullish else "bearish" if bearish else "doji",
        body_to_range=round(body_ratio, 6), close_location=round(close_location, 6),
        upper_wick_to_range=round(upper_ratio, 6), lower_wick_to_range=round(lower_ratio, 6),
        bullish_engulfing=bullish_engulfing, bearish_engulfing=bearish_engulfing,
        inside_bar=inside,
        bullish_rejection=lower_ratio >= 0.50 and close_location >= 0.65,
        bearish_rejection=upper_ratio >= 0.50 and close_location <= 0.35,
        doji=doji, long_legged_doji=long_legged_doji,
        hammer=hammer_shape and bullish, inverted_hammer=inverted_shape and bullish,
        shooting_star=inverted_shape and bearish, hanging_man=hammer_shape and bearish,
        bullish_harami=bullish_harami, bearish_harami=bearish_harami,
        morning_star=morning_star, evening_star=evening_star,
        three_white_soldiers=three_white, three_black_crows=three_black,
        bullish_marubozu=bullish_marubozu, bearish_marubozu=bearish_marubozu,
        bullish_failed_break=bullish_failed_break, bearish_failed_break=bearish_failed_break,
        consecutive_higher_lows=higher_lows, consecutive_lower_highs=lower_highs,
        momentum_long=bullish and body_ratio >= 0.60 and close_location >= 0.75,
        momentum_short=bearish and body_ratio >= 0.60 and close_location <= 0.25,
        nearest_support=round(support, 6) if support is not None else None,
        nearest_resistance=round(resistance, 6) if resistance is not None else None,
        support_distance_atr=round((current.close - support) / atr, 6) if support is not None else None,
        resistance_distance_atr=round((resistance - current.close) / atr, 6) if resistance is not None else None,
        close_to_fast_ema_atr=round((current.close - fast_ema) / atr, 6) if fast_ema is not None else None,
        close_to_slow_ema_atr=round((current.close - slow_ema) / atr, 6) if slow_ema is not None else None,
        close_to_vwap_atr=round((current.close - vwap) / atr, 6) if vwap is not None else None,
    )
