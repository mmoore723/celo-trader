"""Keep order-capable scans independent of watchlist research duration."""
from __future__ import annotations

import logging

from config.strategy_catalog import (
    enabled_observation_strategy_ids, enabled_reviewed_strategy_ids,
    ensure_reviewed_ticker_coverage,
)
from config.strategy_ticker_recommendations import approved_dynamic_tickers
from scanner import TICKER_BLACKLIST

logger = logging.getLogger("celo_trader.trading_logic")


def scan_universe(watchlist, settings):
    enabled = enabled_reviewed_strategy_ids(settings)
    result = ensure_reviewed_ticker_coverage(
        watchlist, enabled | enabled_observation_strategy_ids(settings),
    )
    result += approved_dynamic_tickers(settings, enabled)
    return list(dict.fromkeys(t for t in result if t not in TICKER_BLACKLIST))


def execution_tickers(watchlist, settings):
    return [ticker for ticker in scan_universe(watchlist, settings)
            if enabled_reviewed_strategy_ids(settings, ticker=ticker)]


def seconds_until_scan(now):
    """Retry forming/delayed bars at ten-second boundaries, without catch-up orders."""
    second = now.second + now.microsecond / 1_000_000
    return max(1.0, 10.0 - second % 10.0)


def run_execution_batch(watchlist, settings, stop, tick, alpaca, tradier):
    for ticker in execution_tickers(watchlist, settings) or [""]:
        if stop.is_set():
            break
        tick(alpaca, tradier, scan_ticker=ticker, execution_only=True)


def record_scan_timing(state, ticker, frame, now):
    """Report actual closed-bar coverage, not a successful HTTP request."""
    import pandas as pd
    cutoff = pd.Timestamp(now).tz_localize(None).floor("min")
    times = pd.to_datetime(frame["time"])
    if times.dt.tz is not None:
        times = times.dt.tz_convert("America/New_York").dt.tz_localize(None)
    closed = times[(times < cutoff) & (times.dt.date == cutoff.date())]
    if closed.empty:
        return
    latest = closed.max()
    cache = state.setdefault("execution_scan_coverage", {})
    previous = cache.get(ticker)
    if previous and pd.Timestamp(previous).date() != latest.date():
        previous = None  # Overnight/weekend closure is not a missed scan.
    stale_seconds = max(0.0, (cutoff - latest).total_seconds() - 60.0)
    skipped = max(0, int((latest - pd.Timestamp(previous)).total_seconds() / 60) - 1) if previous else 0
    if previous != latest.isoformat() or stale_seconds:
        logger.log(logging.WARNING if skipped or stale_seconds else logging.INFO,
                   "execution_scan ticker=%s closed_bar=%s skipped_bars=%d stale_seconds=%.1f",
                   ticker, latest.isoformat(), skipped, stale_seconds)
    cache[ticker] = latest.isoformat()
