"""
backtest_data_cache/raw_cache.py — Raw-bars cache (2026-07-23).

The full bundle cache in bundle_cache.py is backtester.py-specific (RVOL/
EMA50/ATR already computed, 1h/15m/1m timeframes attached). The standalone
scripts/diagnostics/diag_*.py scripts fetch their own plain 5-min bars with
a DIFFERENT, simpler indicator set and never touched the bundle cache at
all — every run re-fetched from yfinance/Alpaca from scratch, even though
diag_mid_brk_session_scan.py always requests the same fixed 59-day window.
This is a plain "raw OHLCV DataFrame" cache any script can use before
computing its own indicators on top — the fetch (network I/O) is the slow
part, not the indicator math.

Split out of the old single backtest_data_cache.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

import logging
import pickle
from datetime import date
from pathlib import Path

from backtest_data_cache.constants import _CACHE_DIR

logger = logging.getLogger("celo_trader.backtest_data_cache")


def _raw_path(ticker: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{ticker}_raw5m_{date.today().isoformat()}.pkl"


def load_raw_bars(ticker: str):
    """Return the cached raw 5-min OHLCV DataFrame, or None on any miss."""
    path = _raw_path(ticker)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            df = pickle.load(f)
        logger.info("Raw-bars cache HIT for %s — skipping fetch", ticker)
        return df
    except Exception as ex:
        logger.debug("Raw-bars cache read failed for %s: %s", ticker, ex)
        return None


def save_raw_bars(ticker: str, df) -> None:
    """Persist a raw 5-min OHLCV DataFrame for same-day reuse by ANY script."""
    try:
        with open(_raw_path(ticker), "wb") as f:
            pickle.dump(df, f)
        logger.info("Raw-bars cache SAVED for %s", ticker)
    except Exception as ex:
        logger.debug("Raw-bars cache write failed for %s: %s", ticker, ex)
