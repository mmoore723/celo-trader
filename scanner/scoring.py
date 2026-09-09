"""
scanner/scoring.py — scanner scoring helpers and the once-per-day scan entry.

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging

from scanner.constants import ANCHOR_TICKERS, TICKER_BLACKLIST, _ETF_SET, _ATR_MIN_DOLLARS, _ATR_MIN_PCT
from scanner.helpers import _et_now, _compute_atr
from scanner.state_io import _read_daily_universe
from scanner.premarket import daily_premarket_scan
from scanner.universe import complete_daily_collection_universe

logger = logging.getLogger("celo_trader.scanner")


def _score_ticker(bars: list[dict], ticker: str) -> float:
    """
    Intra-session rescore: RVOL × momentum × liquidity bonus.
    Used for Phase 2 re-ranking within the already-selected universe.
    Returns 0.0 if bars are insufficient or ATR is too low.
    """
    if not bars or len(bars) < 5:
        return 0.0

    atr_usd, atr_pct = _compute_atr(bars)
    if atr_usd < _ATR_MIN_DOLLARS and atr_pct < _ATR_MIN_PCT:
        logger.debug(
            "Scanner rescore: %s ATR=$%.2f (%.2f%%) below thresholds — score=0",
            ticker, atr_usd, atr_pct * 100,
        )
        return 0.0

    volumes = [float(b.get("v", 0)) for b in bars]
    avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    cur_vol = volumes[-1]
    rvol    = cur_vol / avg_vol if avg_vol > 0 else 0.0

    try:
        first_open = float(bars[0].get("o", bars[0].get("c", 0)))
        last_close = float(bars[-1].get("c", 0))
        momentum   = abs(last_close - first_open) / first_open if first_open > 0 else 0.0
    except (TypeError, ZeroDivisionError):
        momentum = 0.0

    liquidity = 1.15 if ticker in _ETF_SET else 1.0
    return round(rvol * momentum * liquidity, 6)


# ── Public API ────────────────────────────────────────────────────────────────

def run_scan(alpaca, max_tickers: int = 30) -> list[str]:
    """
    Entry point called by trading_logic._tick() and _evaluate_signals().

    The first call of the trading day discovers the optionable universe and
    writes the strategy-balanced shortlist. Every later call returns that same
    persisted universe in the same order. Intraday prices may refresh, but the
    membership and priority chosen by the morning scanner stay locked.

    Returns a list of ticker strings, highest priority first.
    """
    today_str = _et_now().strftime("%Y-%m-%d")
    daily     = _read_daily_universe()

    if daily.get("date") != today_str or not daily.get("universe"):
        logger.info("run_scan: no fresh daily universe — triggering daily_premarket_scan")
        return daily_premarket_scan(alpaca, max_tickers)

    # Always include user-pinned tickers even if an older daily payload omitted
    # them. Do not rewrite scanner_state.json here: doing so made a page refresh
    # look like a new scan and moved tickers around after the opening bell.
    try:
        from config import get_settings as _get_s2
        _pins2 = [
            t.upper().strip()
            for t in (_get_s2().get("watchlist") or [])
            if t.strip() and t.strip().upper() not in TICKER_BLACKLIST
        ]
    except Exception:
        _pins2 = []

    # ``scan_details`` is part of the Daily Brief contract. Include it even
    # when this process is reading an older daily file whose capped ``universe``
    # omitted displayed dynamic candidates.
    current_universe = complete_daily_collection_universe(
        daily, user_pins=_pins2,
    )

    watchlist = _pins2 + [
        ticker for ticker in current_universe
        if ticker not in TICKER_BLACKLIST and ticker not in _pins2
    ]
    if not watchlist:
        watchlist = list(ANCHOR_TICKERS)

    logger.info("scan_locked_reused", extra={"event": "scan_locked_reused", "watchlist": watchlist})
    return watchlist
