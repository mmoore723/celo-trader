"""Market-data collection that is independent from entry eligibility."""
from __future__ import annotations

import logging
from typing import Any

from database import record_scanner_candles
from signals import bars_to_df

logger = logging.getLogger("celo_trader.research_collection")


def collect_watchlist_session_bars(
    alpaca: Any,
    tickers: list[str],
    *,
    broker_account_id: str | None = None,
) -> set[str]:
    """Fetch and archive every ticker before order/risk gates can return.

    The normal evaluator records eligible tickers first; the loop calls this
    function afterward only for missing names. A full account, cooldown,
    daily-loss guard, or earnings guard may stop an order, but cannot stop
    collection of the underlying one-minute evidence needed for replay.
    """
    seen: set[str] = set()
    archived: set[str] = set()
    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            bars, is_error, is_live = alpaca.get_session_bars(ticker, "1Min")
            if is_error or not bars:
                logger.warning("research collection has no one-minute bars for %s", ticker)
                continue
            frame = bars_to_df(bars)
            record_scanner_candles(
                ticker,
                frame,
                broker_account_id=broker_account_id,
            )
            archived.add(ticker)
        except Exception:
            logger.warning("research collection failed for %s", ticker, exc_info=True)
    return archived
