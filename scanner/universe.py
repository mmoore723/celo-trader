"""One source of truth for tickers displayed and collected each session."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from scanner.constants import ANCHOR_TICKERS, TICKER_BLACKLIST


def _normalized_unique(*groups: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            ticker = str(value or "").strip().upper()
            if not ticker or ticker in TICKER_BLACKLIST or ticker in seen:
                continue
            seen.add(ticker)
            result.append(ticker)
    return result


def build_collection_universe(
    *, user_pins: Iterable[object], dynamic_tickers: Iterable[object],
) -> list[str]:
    """Return every ticker the product may show as a current trade candidate.

    ``dynamic_tickers`` is already limited to the scanner's configured top-N.
    Pins and anchors are obligations, not replacements for dynamic candidates,
    so this function never trims one group to make room for another.
    """
    return _normalized_unique(user_pins, ANCHOR_TICKERS, dynamic_tickers)


def complete_daily_collection_universe(
    daily: Mapping[str, object], *, user_pins: Iterable[object] = (),
) -> list[str]:
    """Repair/read a persisted daily universe using its displayed scan rows.

    Older files capped ``universe`` after prepending pinned tickers, even though
    ``scan_details`` still exposed every top-ranked name in the Daily Brief.
    Reading both fields keeps restarts and mid-session deployments from losing
    collection coverage before the next morning's scan rewrites the file.
    """
    persisted = daily.get("universe") or []
    if not isinstance(persisted, list):
        persisted = []
    details = daily.get("scan_details") or []
    detail_tickers = [
        row.get("ticker")
        for row in details
        if isinstance(row, Mapping) and row.get("ticker")
    ] if isinstance(details, list) else []
    return _normalized_unique(user_pins, persisted, ANCHOR_TICKERS, detail_tickers)
