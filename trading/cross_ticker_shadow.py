"""Isolated prospective evaluation of reviewed rules on unvalidated tickers.

This module deliberately sits outside the hash-locked reviewed strategy
implementations.  It may *observe* an exact reviewed rule on another ticker,
but it never grants execution permission and never returns a signal to the
order-facing strategy set.  The router's candidate observer is the only
consumer of signals produced here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, MutableMapping

import pandas as pd

from strategies.base import Signal


_VALIDATED_ALIAS = {
    "V2_SPY_TREND_CONT": "SPY",
    "V2_SPY_AFTERNOON_FVG": "SPY",
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": "SPY",
    "CTX_ORB_NR7_OR_INSIDE": "SPY",
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG": "SPY",
    "CTX_VWAP_PULLBACK_KER10_LONG": "SPY",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG": "TSLA",
    "CTX_1H_SQUEEZE_MACD_LONG": "QQQ",
}


def evaluate_bar_strategy(
    strategy_id: str,
    evaluator: Callable[..., Signal | None],
    today: pd.DataFrame,
    *,
    ticker: str,
    account_scope: str,
) -> Signal | None:
    """Evaluate identical signal logic with an isolated dedupe namespace.

    The validated ticker alias only passes the implementation's hard guard;
    ``today`` remains the actual ticker's candles and the caller continues to
    persist the actual ticker.  The distinct scope prevents shadow evaluation
    from consuming a validated ticker's live signal dedupe state.
    """
    alias = _VALIDATED_ALIAS.get(strategy_id)
    if alias is None:
        return None
    return evaluator(
        today,
        ticker=alias,
        execution_scope=f"cross_ticker_shadow:{account_scope}:{ticker.upper()}",
    )


def update_orb(
    state: MutableMapping[str, object], today: pd.DataFrame, *,
    ticker: str, quote_price: float | None, now: datetime,
) -> tuple[Signal | None, str]:
    """Run the exact TSLA ORB rule on another ticker for observation only."""
    from trading.orb_retouch_execution import update_one_minute_orb_retouch
    return update_one_minute_orb_retouch(
        state, today, ticker="TSLA", quote_price=quote_price, now=now,
    )


def update_two_leg(
    state: MutableMapping[str, object], today: pd.DataFrame, *,
    ticker: str, now: datetime,
) -> tuple[Signal | None, str]:
    """Run the exact TSLA two-leg rule on another ticker for observation only."""
    from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback
    return update_two_leg_trend_pullback(state, today, ticker="TSLA", now=now)
