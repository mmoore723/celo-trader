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

FIX 2026-07-23 (still slow across DIFFERENT scripts, not just within one):
the cache key used to be ticker + months + date. But backtester.py's fetch
window is `min(months * 30, 59)` — a yfinance 5-min-bar hard limit — so
months=2 and months=3 (and every months>=2) fetch the IDENTICAL 59-day
window. Keying by the raw `months` value meant ab_test_mid_brk_rvol_ceiling.py
(months=2) and ab_test_mid_brk_session_window.py (months=3) never shared a
cache entry despite pulling the exact same candles. Now keyed by the
EFFECTIVE window (`max_days`), computed the same way backtester.py computes
its fetch range, so every script that resolves to the same real window
shares one cache entry regardless of what `months` value it passed in.

This is a pure I/O-layer cache. It does not touch simulation logic, entry/
exit rules, gating, or any strategy code — only the fetch-and-precompute
step that happens once at the top of Backtester.run(). Same-day-only: keyed
by ticker + effective window + today's date, so a rerun tomorrow (when new
bars exist) always refetches.

Usage (see backtester.py's _load_market_data()):
    bundle = backtest_data_cache.load(ticker, max_days)
    if bundle is not None:
        df, df_1h, df_15m, df1m, day1m_start, df5m_full, day5m_start = (
            bundle["df"], bundle["df_1h"], ... )
    else:
        # ... fetch + compute as before ...
        backtest_data_cache.save(ticker, max_days, df=df, df_1h=df_1h, ...)
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


def max_days_for(months: int) -> int:
    """
    The EFFECTIVE fetch window for a given `months` request — same formula
    backtester.py uses for its yfinance fetch range. Exposed here so both
    backtester.py and this module compute it identically; if they ever drift,
    the cache key and the real fetch window silently stop matching.
    """
    return min(months * 30, 59)   # yfinance 5-min-bar hard limit = 60 days


def _cache_path(ticker: str, max_days: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{ticker}_{max_days}d_{date.today().isoformat()}.pkl"


def load(ticker: str, max_days: int) -> Optional[dict]:
    """
    Return the cached bundle dict, or None on any cache miss / read failure.
    A miss (not an exception) is the expected, common path — callers should
    just fall through to a real fetch, never treat None as an error.

    `max_days` must be the EFFECTIVE fetch window (see max_days_for above),
    not a raw `months` value — that's what makes a months=2 script and a
    months=3 script share one cache entry when both resolve to the same
    59-day yfinance cap.
    """
    path = _cache_path(ticker, max_days)
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
) -> None:
    """
    Persist the fetched/precomputed dataframes for same-day reuse. Never
    raises — a failed cache write should never break a backtest run, it just
    means the next Backtester construction re-fetches instead of reusing.
    """
    path = _cache_path(ticker, max_days)
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


# ── Raw-bars cache (2026-07-23) ────────────────────────────────────────────────
# The full bundle cache above is backtester.py-specific (RVOL/EMA50/ATR
# already computed, 1h/15m/1m timeframes attached). The standalone
# scripts/diagnostics/diag_*.py scripts fetch their own plain 5-min bars
# with a DIFFERENT, simpler indicator set and never touched the bundle cache
# at all — every run re-fetched from yfinance/Alpaca from scratch, even
# though diag_mid_brk_session_scan.py always requests the same fixed 59-day
# window. This is a plain "raw OHLCV DataFrame" cache any script can use
# before computing its own indicators on top — the fetch (network I/O) is
# the slow part, not the indicator math.

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
