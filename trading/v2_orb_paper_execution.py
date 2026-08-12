"""Execution-price rules for the V2 TSLA ORB paper-validation cohort.

The paid study deliberately assumed the conservative executable side of each
quote: buy at ask and sell at bid.  The normal bot uses a mid-price improvement
attempt before crossing the spread, which is reasonable execution logic but
would make a V2 paper result incomparable with that study.  These pure helpers
keep the stricter choice narrowly scoped and easy to regression-test.
"""
from __future__ import annotations

from typing import Optional


def entry_limit_prices(*, ask: float, midpoint: float, v2_paper_pilot: bool) -> tuple[float, Optional[float]]:
    """Return (initial_limit, step_to_price) for an option buy."""
    if ask <= 0 or midpoint <= 0:
        raise ValueError("entry prices must be positive")
    if v2_paper_pilot:
        return round(ask, 2), None
    return round(midpoint, 2), round(ask, 2)


def exit_limit_prices(*, bid: float, midpoint: float, v2_paper_pilot: bool) -> tuple[float, Optional[float]]:
    """Return (initial_limit, step_to_price) for an option sell."""
    if bid <= 0 or midpoint <= 0:
        raise ValueError("exit prices must be positive")
    if v2_paper_pilot:
        return round(bid, 2), None
    return round(midpoint, 2), round(bid, 2)


def include_reviewed_tickers_when_v2_pilots_enabled(
    watchlist: list[str], *, enabled_strategy_ids: set[str],
) -> list[str]:
    """Append only the validated symbols needed by enabled reviewed pilots."""
    from config.strategy_catalog import ensure_reviewed_ticker_coverage
    return ensure_reviewed_ticker_coverage(watchlist, enabled_strategy_ids)


def include_tsla_when_v2_pilot_enabled(watchlist: list[str], *, v2_paper_pilot: bool) -> list[str]:
    """Backward-compatible TSLA helper retained for the original pilot tests."""
    return include_reviewed_tickers_when_v2_pilots_enabled(
        watchlist,
        enabled_strategy_ids={"V2_ORB_PULLBACK"} if v2_paper_pilot else set(),
    )
