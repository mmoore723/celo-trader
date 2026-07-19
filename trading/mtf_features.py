"""
trading/mtf_features.py — Shared multi-timeframe indicator functions.

Extracted from trading/position_manager.py (2026-07-18). The adaptive exit
engine already computed RSI / MACD / ADX / EMA-stack-alignment / 1-hour trend
bias live for every open position; this module pulls those five functions
out so the entry path (ai_reasoning/decision_support.py, phase 2 of the AI
reasoning layer) can call the SAME functions before a trade opens, instead of
a second copy that could quietly drift out of sync with the exit engine's
math over time. This is a pure move — no formula changed. position_manager.py
now imports these instead of defining them locally.

Every function is defensive: bad/short input returns None (or a neutral
default) instead of raising, because these run inside the live trading
loop's tick — a crash here must never take down position management or
signal evaluation.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("celo_trader.trading.mtf_features")

# ── EMA-stack constants (used only by ema_stack_aligned below) ───────────────
_EMA_FAST = 8
_EMA_MID  = 21
_EMA_SLOW = 50


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Wilder's ADX on 1-min bars.
    ADX < 20 = no directional trend (choppy / ranging).
    """
    try:
        if len(df) < period * 2:
            return None
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)
        close = df["close"].values.astype(float)

        # True Range
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )

        # Directional movement
        plus_dm  = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                             np.maximum(high[1:] - high[:-1], 0), 0)
        minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                             np.maximum(low[:-1] - low[1:], 0), 0)

        # Wilder smoothing (EMA with alpha = 1/period)
        def wilder_smooth(arr, n):
            out = np.zeros(len(arr))
            out[0] = arr[:n].sum()
            for i in range(1, len(arr)):
                out[i] = out[i-1] - out[i-1] / n + arr[i]
            return out

        atr_w  = wilder_smooth(tr, period)
        pdm_w  = wilder_smooth(plus_dm, period)
        mdm_w  = wilder_smooth(minus_dm, period)

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi    = np.where(atr_w > 0, 100 * pdm_w / atr_w, 0)
            mdi    = np.where(atr_w > 0, 100 * mdm_w / atr_w, 0)
            dx_den = pdi + mdi
            dx     = np.where(dx_den > 0, 100 * np.abs(pdi - mdi) / dx_den, 0)

        adx_w  = wilder_smooth(dx[period:], period)
        return float(adx_w[-1]) if len(adx_w) > 0 else None
    except Exception as ex:
        logger.debug("ADX computation failed: %s", ex)
        return None


def ema_stack_aligned(df: pd.DataFrame, direction: str) -> bool:
    """
    True if the EMA stack is aligned in the trade direction.

    Bullish (CALL): EMA8 > EMA21 > EMA50 — all stacked up
    Bearish (PUT) : EMA8 < EMA21 < EMA50 — all stacked down

    Misalignment means the trend is breaking down and a VWAP breach is
    meaningful (used by the exit engine) or that momentum doesn't support
    a fresh entry yet (used by phase 2 decision support).
    """
    try:
        if len(df) < _EMA_SLOW + 5:
            return True   # insufficient data → assume aligned (don't block/exit prematurely)
        close = df["close"]
        ema8  = float(close.ewm(span=_EMA_FAST, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=_EMA_MID,  adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=_EMA_SLOW, adjust=False).mean().iloc[-1])
        if direction == "bullish":
            return ema8 > ema21 > ema50
        else:
            return ema8 < ema21 < ema50
    except Exception:
        return True


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """RSI on the most recent bar. Returns None if insufficient history."""
    try:
        if len(df) < period + 2:
            return None
        close = df["close"].astype(float)
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, np.nan)
        rsi   = 100.0 - (100.0 / (1.0 + rs))
        val   = float(rsi.iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def compute_macd_hist(df: pd.DataFrame,
                       fast: int = 12, slow: int = 26, sig: int = 9) -> list:
    """Returns last 3 MACD histogram values (most recent last). Empty list if not enough data."""
    try:
        if len(df) < slow + sig:
            return []
        close     = df["close"].astype(float)
        ema_fast  = close.ewm(span=fast, adjust=False).mean()
        ema_slow  = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        sig_line  = macd_line.ewm(span=sig, adjust=False).mean()
        hist      = (macd_line - sig_line).tolist()
        return hist[-3:]
    except Exception:
        return []


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
