"""
backtester_1min_entry.py — Fetches and prepares 1-minute bar data for entry-
resolution testing, matching live's actual signal-detection pipeline.

WHY THIS EXISTS: live's trading/entry.py scans for entry signals on 1-minute
bars ("Switched from 5Min -> 1Min so all 8 strategies detect structure
shifts at the exact candle" — 2026-06-23). backtester.py has always scanned
on 5-minute bars. This module fetches real 1-minute history (via Alpaca,
which — after fixing a bars-per-day bug in broker.py — reliably serves
~36 days, vs. yfinance's hard 8-day 1-minute cap) and builds the exact same
indicator columns strategy_router.py's _build_indicator_frame() computes,
just at 1-minute resolution, so the real strategy evaluators and
router_gates.py functions can run against it unmodified.

Deliberately does NOT copy live's "today 1-min + historical 5-min" hybrid
fetch pattern — that pattern exists because Alpaca's free tier only serves
1-min history for the CURRENT session in real-time polling. For backtesting
we can fetch true multi-day 1-min history directly, which lets us test the
resolution hypothesis across every day in the window, not just the most
recent one.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from signals import bars_to_df, compute_rvol, compute_vwap_bands

logger = logging.getLogger("celo_trader.backtester_1min_entry")

# Alpaca's free/IEX tier reliably serves ~36 days of 1-minute bars (confirmed
# empirically via diag_1min_data_availability.py, 2026-07-21); requests
# implying much further back return HTTP 400. Capped conservatively below
# that confirmed ceiling, not right at the edge.
MAX_1MIN_DAYS = 30

# BUG FIX 2026-07-21: MAX_1MIN_DAYS=30 alone isn't enough to stay safe — the
# LIMIT passed to broker.py's get_bars() has to account for broker.py's own
# padding math (calendar_days_back = ceil(limit/390 bars-per-day) * 1.6 +
# 3, padding for weekends/holidays). A naive `30 days * 390 bars/day` limit
# computes a calendar start ~51 days back, well past the confirmed ~36-37
# day ceiling, and Alpaca returns HTTP 400. Solving backwards for a limit
# that keeps broker.py's own padded start date under the confirmed ceiling
# (with margin): 18 trading days -> ~31 calendar days back. Confirmed safe
# empirically (the 10,000-bar / ~26-calendar-day request succeeded; this is
# smaller than that).
_SAFE_1MIN_LIMIT = 18 * 390  # ~7,020 bars ≈ 18 trading days ≈ 31 calendar days back


def fetch_1min_entry_data(alpaca, ticker: str, months: int) -> Optional[pd.DataFrame]:
    """
    Returns a 1-minute OHLCV DataFrame with the same indicator columns as
    strategy_router.py's _build_indicator_frame() (vwap bands, rvol, ema50,
    atr, vol_sma20), or None if 1-minute data isn't available/sufficient —
    callers should fail open to 5-minute-only behavior in that case, same
    fail-open convention used everywhere else in this app.
    """
    try:
        # `months` is accepted for API-shape consistency with the rest of
        # backtester.py's fetchers but no longer drives the request size —
        # see _SAFE_1MIN_LIMIT's comment for why. Alpaca's actual serving
        # window is the real constraint here, not what the caller asks for.
        _ = months
        bars, is_error = alpaca.get_bars(ticker, "1Min", limit=_SAFE_1MIN_LIMIT)
        if is_error or not bars:
            logger.warning("fetch_1min_entry_data: no 1-min bars for %s — caller should fail open", ticker)
            return None

        df = bars_to_df(bars)
        if df.empty or len(df) < 100:
            logger.warning("fetch_1min_entry_data: insufficient 1-min bars for %s (%d rows)", ticker, len(df))
            return None

        # ── Build the SAME indicator columns _build_indicator_frame() does ────
        # (strategy_router.py) — kept as a parallel implementation, not an
        # import, because that function only returns TODAY's bars (single-day
        # slice); here we need the full multi-day history for backtesting.
        # Same formulas, same column names, just applied across every day.
        _vwap_frame = compute_vwap_bands(df, num_stds=(1, 2))
        df["vwap"]        = _vwap_frame["vwap"].ffill()
        df["vwap_upper1"] = _vwap_frame["vwap_upper1"].ffill()
        df["vwap_lower1"] = _vwap_frame["vwap_lower1"].ffill()
        df["vwap_upper2"] = _vwap_frame["vwap_upper2"].ffill()
        df["vwap_lower2"] = _vwap_frame["vwap_lower2"].ffill()

        rvol_series = compute_rvol(df, lookback_days=10)
        df["rvol"]  = rvol_series.reindex(df.index).fillna(1.0)

        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

        hl  = df["high"] - df["low"]
        hcp = (df["high"] - df["close"].shift(1)).abs()
        lcp = (df["low"]  - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        df["vol_sma20"] = df["volume"].rolling(100, min_periods=20).mean()

        df["_date"] = df["time"].dt.date
        logger.info(
            "fetch_1min_entry_data: %d 1-min bars for %s (%s -> %s)",
            len(df), ticker, df["time"].min(), df["time"].max(),
        )
        return df

    except Exception as ex:
        logger.warning("fetch_1min_entry_data failed for %s (%s) — caller should fail open", ticker, ex)
        return None
