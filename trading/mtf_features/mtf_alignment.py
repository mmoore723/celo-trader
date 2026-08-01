"""
trading/mtf_features/mtf_alignment.py — trend_bias_1h(), compute_mtf_alignment().

Split out of the old single trading/mtf_features.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("celo_trader.trading.mtf_features")


def trend_bias_1h(df_1h: pd.DataFrame, direction: str) -> str:
    """
    Check if 1-hour EMA20 supports the trade direction.
    Returns "with", "against", or "neutral" (insufficient data).

    Despite the name this is just "EMA20 bias for whatever df you pass in" —
    compute_mtf_alignment() below reuses it for 5Min/15Min/1Hour too, rather
    than duplicating the same three lines of math per timeframe.
    """
    try:
        if df_1h is None or len(df_1h) < 22:
            return "neutral"
        close  = df_1h["close"].astype(float)
        ema20  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        price  = float(close.iloc[-1])
        if direction == "bullish":
            return "with" if price > ema20 else "against"
        else:
            return "with" if price < ema20 else "against"
    except Exception:
        return "neutral"


def compute_mtf_alignment(
    alpaca: "AlpacaClient",  # noqa: F821 — type-checking only, avoids a hard import cycle
    ticker: str,
    direction: str,
    df_1m: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Teaching-overlay helper: does higher-timeframe trend bias agree with this
    entry's direction, across 1Min/5Min/15Min/1Hour? Returns a dict of
    {"1Min": "with"|"against"|"neutral", "5Min": ..., "15Min": ..., "1Hour": ...}
    for Journal replay's MTF alignment heat map — NOT fed back into any live
    entry/exit decision (that would be a strategy change, not a chart feature).

    `df_1m`, if given, is reused instead of an extra API call — entry.py
    already fetches 1Min bars for its own signal evaluation right before this
    would be called.

    Meant to be called AFTER a trade is already recorded (best-effort,
    save-only), never before/blocking order placement: each per-timeframe
    fetch is independently wrapped so one slow or failed call can never raise
    or hold up the caller — a missing timeframe just reports "neutral".
    """
    result: dict[str, str] = {}

    if df_1m is not None:
        result["1Min"] = trend_bias_1h(df_1m, direction)
    else:
        result["1Min"] = "neutral"

    for _label, _api_tf in (("5Min", "5Min"), ("15Min", "15Min"), ("1Hour", "1Hour")):
        try:
            _bars, _is_error = alpaca.get_bars(ticker, _api_tf, limit=100)
            if _is_error or not _bars:
                result[_label] = "neutral"
                continue
            from signals import bars_to_df
            _df = bars_to_df(_bars)
            result[_label] = trend_bias_1h(_df, direction)
        except Exception:
            logger.warning("compute_mtf_alignment: %s fetch/compute failed for %s — reporting neutral", _label, ticker, exc_info=True)
            result[_label] = "neutral"

    return result
