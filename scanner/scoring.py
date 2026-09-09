"""
scanner/scoring.py — Phase-2 rescore: _score_ticker (RVOL x momentum x
liquidity-bonus formula) and run_scan (rescores the already-selected
universe, falling back to daily_premarket_scan if the watchlist is empty).

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging

from scanner.constants import ANCHOR_TICKERS, TICKER_BLACKLIST, _ETF_SET, _ATR_MIN_DOLLARS, _ATR_MIN_PCT
from scanner.helpers import _et_now, _compute_atr
from scanner.state_io import _read_daily_universe, _write_state
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

    First premarket call and first call after 9:30 ET:
        Runs daily_premarket_scan() against the active optionable universe and
        writes today's strategy-balanced research shortlist to disk.

    Subsequent calls:
        Rescores the already-selected universe by live 5-min RVOL × momentum so
        the hottest mover is evaluated first each tick.

    Returns a list of ticker strings, highest priority first.
    """
    today_str = _et_now().strftime("%Y-%m-%d")
    daily     = _read_daily_universe()

    # ── Phase 1: full scan (once per session, after market open) ─────────────
    regular_refresh_due = (
        daily.get("scan_meta", {}).get("phase") == "premarket"
        and (_et_now().hour * 60 + _et_now().minute) >= 9 * 60 + 30
    )
    if daily.get("date") != today_str or not daily.get("universe") or regular_refresh_due:
        logger.info("run_scan: no fresh daily universe — triggering daily_premarket_scan")
        return daily_premarket_scan(alpaca, max_tickers)

    # ── Phase 2: rescore existing dynamic universe ────────────────────────────
    # Always include user-pinned tickers even if they weren't in today's scan.
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

    scores: dict[str, float] = {}
    for ticker in current_universe:
        try:
            bars, err = alpaca.get_bars(ticker, "5Min", limit=25)
            if err or not bars:
                scores[ticker] = 0.0
                continue
            scores[ticker] = _score_ticker(bars, ticker)
        except Exception as ex:
            logger.warning("Scanner rescore error for %s: %s", ticker, ex)
            scores[ticker] = 0.0

    ranked = sorted(scores, key=lambda t: scores[t], reverse=True)
    # Pinned tickers always lead the list regardless of their score
    watchlist = _pins2 + [t for t in ranked if t not in TICKER_BLACKLIST and t not in _pins2]
    if not watchlist:
        watchlist = [t for t in current_universe if t not in TICKER_BLACKLIST]
    if not watchlist:
        watchlist = list(ANCHOR_TICKERS)

    _write_state(watchlist, scores)
    logger.info(
        "scan_rescore",
        extra={"event": "scan_rescore", "watchlist": watchlist,
               "top_scores": {t: scores.get(t, 0) for t in watchlist[:5]}},
    )
    return watchlist
