"""
backtest_data_cache.py — same-day disk cache for backtester.py's fetched
market data (5-min bars + indicators, 1-min entry bars, 1h/15m extra
timeframes, and the day-start index maps built from them).

WHY THIS EXISTS (2026-07-22): the A/B test scripts (ab_test_rr_gate.py,
ab_test_structural_stop_mode.py) construct a fresh Backtester per ticker,
once PER VARIANT — 4 to 5 times per script run. Only the STRATEGY LOGIC
differs between variants; the underlying candles (yfinance/Alpaca 5-min
bars, 1-min entry bars, 1h/15m extra timeframes) are identical every time.
Without this cache, every variant re-fetches and re-computes indicators
(RVOL/EMA50/ATR/ADX) on the exact same data — pure waste, and the user
correctly called this out after a 5-hour run.

This is a pure I/O-layer cache. It does not touch simulation logic, entry/
exit rules, gating, or any strategy code — only the fetch-and-precompute
step that happens once at the top of Backtester.run(). Same-day-only, same
pattern as run_full_audit.py's result cache: keyed by ticker + months +
today's date, so a rerun tomorrow (when new bars exist) always refetches.

Usage (see backtester.py's _load_market_data()):
    bundle = backtest_data_cache.load(ticker, months)
    if bundle is not None:
        df, df_1h, df_15m, df1m, day1m_start, df5m_full, day5m_start = (
            bundle["df"], bundle["df_1h"], ... )
    else:
        # ... fetch + compute as before ...
        backtest_data_cache.save(ticker, months, df=df, df_1h=df_1h, ...)
"""

from __future__ import annotations

import logging
import pickle
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger("celo_trader.backtest_data_cache")

_CACHE_DIR = Path("audit_reports") / "_data_cache"

# Bump this if the bundle's shape ever changes, so stale-shaped pickles from
# an older version of this file are ignored instead of crashing a restore.
_BUNDLE_VERSION = 1


def _cache_path(ticker: str, months: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{ticker}_{months}mo_{date.today().isoformat()}.pkl"


def load(ticker: str, months: int) -> Optional[dict]:
    """
    Return the cached bundle dict, or None on any cache miss / read failure.
    A miss (not an exception) is the expected, common path — callers should
    just fall through to a real fetch, never treat None as an error.
    """
    path = _cache_path(ticker, months)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        if bundle.get("_version") != _BUNDLE_VERSION:
            return None
        logger.info(
            "Backtest data cache HIT for %s (%dmo) — skipping fetch + indicator recompute",
            ticker, months,
        )
        return bundle
    except Exception as ex:
        logger.debug("Backtest data cache read failed for %s (%dmo): %s", ticker, months, ex)
        return None


def save(
    ticker: str,
    months: int,
    df,
    df_1h,
    df_15m,
    df1m,
    day1m_start: dict,
    df5m_full,
    day5m_start: dict,
) -> None:
    """
    Persist the fetched/precomputed dataframes for same-day reuse. Never
    raises — a failed cache write should never break a backtest run, it just
    means the next Backtester construction re-fetches instead of reusing.
    """
    path = _cache_path(ticker, months)
    bundle = {
        "_version":    _BUNDLE_VERSION,
        "df":          df,
        "df_1h":       df_1h,
        "df_15m":      df_15m,
        "df1m":        df1m,
        "day1m_start": day1m_start,
        "df5m_full":   df5m_full,
        "day5m_start": day5m_start,
    }
    try:
        with open(path, "wb") as f:
            pickle.dump(bundle, f)
        logger.info("Backtest data cache SAVED for %s (%dmo)", ticker, months)
    except Exception as ex:
        logger.debug("Backtest data cache write failed for %s (%dmo): %s", ticker, months, ex)
