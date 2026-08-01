"""
backtest_data_cache/bundle_cache.py — same-day disk cache for backtester.py's
fully-precomputed market-data bundle (5-min bars + indicators, 1-min entry
bars, 1h/15m extra timeframes, and the day-start index maps built from them).

Split out of the old single backtest_data_cache.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

import logging
import pickle
from datetime import date
from pathlib import Path
from typing import Optional

from backtest_data_cache.constants import _CACHE_DIR, _BUNDLE_VERSION

logger = logging.getLogger("celo_trader.backtest_data_cache")


def _cache_path(ticker: str, max_days: int, as_of: date | None = None) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    anchor = as_of or date.today()
    return _CACHE_DIR / f"{ticker}_{max_days}d_{anchor.isoformat()}.pkl"


def load(ticker: str, max_days: int, as_of: date | None = None) -> Optional[dict]:
    """
    Return the cached bundle dict, or None on any cache miss / read failure.
    A miss (not an exception) is the expected, common path — callers should
    just fall through to a real fetch, never treat None as an error.

    `max_days` must be the EFFECTIVE fetch window (see max_days_for in
    constants.py), not a raw `months` value — that's what makes a months=2
    script and a months=3 script share one cache entry when both resolve to
    the same 59-day yfinance cap.
    """
    path = _cache_path(ticker, max_days, as_of)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        if bundle.get("_version") != _BUNDLE_VERSION:
            return None
        logger.info(
            "Backtest data cache HIT for %s (%dd window) — skipping fetch + indicator recompute",
            ticker, max_days,
        )
        return bundle
    except Exception as ex:
        logger.debug("Backtest data cache read failed for %s (%dd): %s", ticker, max_days, ex)
        return None


def save(
    ticker: str,
    max_days: int,
    df,
    df_1h,
    df_15m,
    df1m,
    day1m_start: dict,
    df5m_full,
    day5m_start: dict,
    as_of: date | None = None,
) -> None:
    """
    Persist the fetched/precomputed dataframes for same-day reuse. Never
    raises — a failed cache write should never break a backtest run, it just
    means the next Backtester construction re-fetches instead of reusing.
    """
    path = _cache_path(ticker, max_days, as_of)
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
        logger.info("Backtest data cache SAVED for %s (%dd window)", ticker, max_days)
    except Exception as ex:
        logger.debug("Backtest data cache write failed for %s (%dd): %s", ticker, max_days, ex)
