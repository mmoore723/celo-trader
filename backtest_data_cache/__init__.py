"""
backtest_data_cache/ — same-day disk cache for backtester.py's fetched
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

Split further out of the old single backtest_data_cache.py (2026-08-01,
file-size cleanup) into:
  - constants.py:   _CACHE_DIR, _BUNDLE_VERSION, max_days_for()
  - bundle_cache.py: load(), save() — backtester.py's fully-precomputed bundle
  - raw_cache.py:    load_raw_bars(), save_raw_bars() — plain OHLCV, for
                       standalone diagnostics scripts

No monkeypatching of this module's names was found anywhere in the
codebase (grep-verified) — the two external consumers (backtester/
market_data.py and scripts/diagnostics/diag_mid_brk_session_scan.py) both
use whole-module dotted access (`import backtest_data_cache; ...load(...)`),
which works unchanged against a package as long as __init__.py re-exports
these names, which it does below.
"""
from __future__ import annotations

from backtest_data_cache.constants import _CACHE_DIR, _BUNDLE_VERSION, max_days_for
from backtest_data_cache.bundle_cache import load, save
from backtest_data_cache.raw_cache import load_raw_bars, save_raw_bars

__all__ = [
    "max_days_for",
    "load",
    "save",
    "load_raw_bars",
    "save_raw_bars",
]
