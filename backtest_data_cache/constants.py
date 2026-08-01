"""
backtest_data_cache/constants.py — cache dir, bundle version, and the
effective-window formula shared by both the bundle cache and raw-bars cache.

Split out of the old single backtest_data_cache.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

from pathlib import Path

_CACHE_DIR = Path("audit_reports") / "_data_cache"

# Bump this if the bundle's shape ever changes, so stale-shaped pickles from
# an older version of this file are ignored instead of crashing a restore.
_BUNDLE_VERSION = 2


def max_days_for(months: int) -> int:
    """
    The EFFECTIVE fetch window for a given `months` request — same formula
    backtester.py uses for its yfinance fetch range. Exposed here so both
    backtester.py and this module compute it identically; if they ever drift,
    the cache key and the real fetch window silently stop matching.
    """
    return min(months * 30, 59)   # yfinance 5-min-bar hard limit = 60 days
