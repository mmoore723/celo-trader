"""
trading/mtf_live_gate.py — Lightweight LIVE 1-hour trend-bias confirmation.

Gap 3 from the 2026-07-23 professional-strategy-alignment audit: published
sources say a break-of-structure confirmed on a HIGHER timeframe (4H/Daily)
is far more reliable than intraday-only. This bot already computes multi-
timeframe bias (trading/mtf_features.py::compute_mtf_alignment) — but that
function is explicitly documented as post-hoc-only, called AFTER a trade is
already recorded, because fetching 5Min/15Min/1Hour bars on every single
signal evaluation would mean 3 extra live API calls per tick per ticker.
That was the right call at the time; it just left the live entry path with
no higher-timeframe confirmation at all.

This module makes ONE of those timeframes — 1Hour, the cheapest and the one
sources weight most — safe to use live, by caching the result per ticker and
refreshing at most every _REFRESH_SEC seconds instead of on every tick.

IMPORTANT — this gate cannot be backtested the same way every other toggle
in this codebase was: backtester.py replays historical multi-day data, it
doesn't make live "as-of-now" API calls the way this cache does. There is no
clean historical A/B for this one. That's why it ships as a SOFT confidence
adjustment (never a hard block) and OFF by default — watch it in
signal_only_mode before trusting it to gate real entries.
"""

from __future__ import annotations

import logging
import time

from trading.mtf_features import trend_bias_1h

logger = logging.getLogger("celo_trader.trading.mtf_live_gate")

_REFRESH_SEC = 15 * 60   # re-fetch 1Hour bars at most every 15 min per ticker


def get_live_1h_bias(alpaca, ticker: str, direction: str, cache: dict) -> str:
    """
    Return "with" / "against" / "neutral" for the 1Hour EMA20 bias.

    `cache` is a plain dict, owned by the caller (trading/state.py's per-user
    state dict under "mtf_1h_cache") — mutated in place so the fetch is
    shared across tickers/ticks instead of re-fetched every call:
        cache[ticker] = {"ts": <epoch seconds>, "price_above_ema20": bool}

    The raw price-vs-EMA20 relationship is cached once, not a per-direction
    verdict — trend_bias_1h() is a strict above/below check, so both
    directions derive from the same single fetch instead of needing two.
    """
    entry = cache.get(ticker)
    now = time.time()

    if entry is None or (now - entry.get("ts", 0)) > _REFRESH_SEC:
        try:
            bars, is_error = alpaca.get_bars(ticker, "1Hour", limit=30)
            if is_error or not bars:
                return "neutral"
            from signals import bars_to_df
            df_1h = bars_to_df(bars)
            price_above_ema20 = trend_bias_1h(df_1h, "bullish") == "with"
            cache[ticker] = {"ts": now, "price_above_ema20": price_above_ema20}
            entry = cache[ticker]
        except Exception:
            logger.debug("get_live_1h_bias: fetch failed for %s — neutral", ticker, exc_info=True)
            return "neutral"

    price_above = entry.get("price_above_ema20")
    if price_above is None:
        return "neutral"
    if direction == "bullish":
        return "with" if price_above else "against"
    return "with" if not price_above else "against"
