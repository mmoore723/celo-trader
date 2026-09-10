"""Describe what the Research Results profit factor actually measures.

The research matrix records common same-contract timer marks for comparison.
Only five reviewed strategies were authored and validated with that timer as
their real exit. The other strategies define a stop/target, trail, flip, or
structural exit that still needs a separate causal option quote.
"""
from __future__ import annotations
from strategy_health.exit_protocols import PROTOCOLS


_EXACT_TIMED_EXITS = frozenset({
    "V2_ORB_PULLBACK",
    "V2_SPY_TREND_CONT",
    "V2_SPY_AFTERNOON_FVG",
    "V2_FAILED_OR_BREAK_VWAP_REVERSION",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK",
})

_AUTHORED_EXITS = {
    "V2_ORB_PULLBACK": "Sell the same option 90 minutes after entry.",
    "V2_SPY_TREND_CONT": "Sell the same option 30 minutes after entry.",
    "V2_SPY_AFTERNOON_FVG": "Sell the same option 30 minutes after entry.",
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": "Sell the same option 30 minutes after entry.",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": "Sell the same option 90 minutes after entry.",
    "CTX_ORB_NR7_OR_INSIDE": "Take part at +30%, the rest at +100%, or exit when price closes through the opening-range middle.",
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG": "Take part at +30%, the rest at +100%, or exit when price closes through the opening-range middle.",
    "CTX_VWAP_PULLBACK_KER10_LONG": "Exit at the prior high or when a completed 5-minute candle closes below VWAP.",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG": "Exit at the frozen prior high, a completed 5-minute close below VWAP, or 3:55 PM.",
    "CTX_1H_SQUEEZE_MACD_LONG": "Exit at +150% option profit or when an hourly candle closes back inside the 20-SMA.",
    "V2_AFTERNOON_COMPRESSION_BREAKOUT": "Exit at the signal's structural stop or 2R target.",
    "V2_AFTERNOON_REVERSAL": "Check the original stop and 2R target at each 5-minute close; exit by market close.",
    "V2_EMA_PULLBACK_RTH": "Exit at the signal's structural stop or 2.06R target.",
    "V2_FAIR_VALUE_GAP": "Check the original stop and 2R target at each 5-minute close. This intraday test ends by market close.",
    "V2_GAP_FILL_RTH": "Track the 2-ATR stop on 1-minute candles; tighten after each 5-minute close. No fixed target; exit by session close.",
    "V2_MIDDAY_BREAKDOWN": "Exit at the signal's structural stop or target.",
    "V2_OPENING_MOMENTUM_RTH_EXPLORATORY": "Track the 2-ATR stop on 1-minute candles; tighten after each 5-minute close. No fixed target; exit by session close.",
    "V2_ORB_CONFIRMED_BREAKOUT": "Exit at the opening-range structural stop or 1.5R target.",
    "V2_IMPULSE_ANCHORED_VWAP_PULLBACK": "Exit on a completed 5-minute candle at the structural stop, 2R target, or hold/session limit.",
    "V2_RANGE_SWEEP_RECLAIM": "Exit at the failed-sweep structural stop or the strategy target.",
    "V2_SPY_ORB_RSI_MACD_SHORT": "Exit at the signal's structural stop or target.",
    "V2_TREND_CONT": "Exit on a completed 5-minute candle at the original stop, 2R target, or hold/session limit.",
    "V2_TURTLE_SOUP_RTH": "Exit at the failed-auction structural stop or target.",
    "V2_VWAP_PULLBACK": "Check the original stop and 2R target at each 5-minute close. This intraday test ends by market close.",
    "V2_VWAP_REVERSION_RTH": "Exit at the 4-ATR stop or session VWAP target.",
    "TV_SUPERTREND_REVERSAL_V4": "Exit on the next opposite SuperTrend flip, or at the session close.",
}


def exit_measurement(strategy_id: object, minutes: int) -> dict[str, object]:
    """Return a compact, UI-safe description of the measured exit."""
    normalized = str(strategy_id or "").strip().upper()
    faithful = normalized in _EXACT_TIMED_EXITS
    return {
        "kind": "strategy_exit" if faithful else "timed_comparison",
        "pf_label": f"{minutes}-min PF" if faithful else f"{minutes}-min check PF",
        "timed_minutes": int(minutes),
        "authored_exit": _AUTHORED_EXITS.get(
            normalized, "Exit at the stop or target defined by the strategy.",
        ),
        "authored_exit_collected": faithful,
        "authored_collector_enabled": normalized in PROTOCOLS,
    }
