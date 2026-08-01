"""
scanner/windows.py — Session-window checks (is_premarket_window,
is_scan_window) and watchlist/universe readers (get_watchlist,
get_today_universe) used by the trading loop to decide when to scan.

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import json
import logging
from datetime import datetime

from config import TICKER_UNIVERSE
from scanner.constants import (
    SCANNER_STATE, ANCHOR_TICKERS,
    PREMARKET_START_HM, PREMARKET_END_HM, SESSION_START_HM, SESSION_END_HM,
)
from scanner.helpers import _et_now, _hm_in_range
from scanner.state_io import _read_daily_universe

logger = logging.getLogger("celo_trader.scanner")

def get_watchlist() -> list[str]:
    """
    Read today's scanned watchlist from disk.

    Priority:
    1. daily_universe.json (from today's dynamic scan)
    2. scanner_state.json  (from the most recent rescore)
    3. ANCHOR_TICKERS      (fallback if nothing fresh exists)

    Stale check: the daily universe is valid for the entire trading day.
    The rescore cache expires after 2 hours to catch restart scenarios.
    """
    today_str = _et_now().strftime("%Y-%m-%d")

    # ── Try today's daily universe first ─────────────────────────────────────
    try:
        daily = _read_daily_universe()
        if daily.get("date") == today_str and daily.get("universe"):
            return list(daily["universe"])
    except Exception as ex:
        logger.debug("get_watchlist: daily_universe.json read error: %s", ex)

    # ── Fall back to scanner_state.json (rescore cache) ──────────────────────
    try:
        if not SCANNER_STATE.exists():
            return list(ANCHOR_TICKERS)
        data = json.loads(SCANNER_STATE.read_text())

        written_iso = data.get("written_utc", "")
        if written_iso:
            written_dt = datetime.fromisoformat(written_iso)
            age_hours  = (datetime.utcnow() - written_dt).total_seconds() / 3600
            if age_hours > 2.0:
                logger.debug("Scanner state stale (%.1fh) — using anchors", age_hours)
                return list(ANCHOR_TICKERS)

        wl = data.get("watchlist", [])
        return wl if wl else list(ANCHOR_TICKERS)

    except Exception as ex:
        logger.warning("get_watchlist: scanner_state.json read error: %s — using anchors", ex)
        return list(ANCHOR_TICKERS)


def get_today_universe() -> list[str]:
    """
    Return today's dynamic ticker universe (from daily_premarket_scan).
    Falls back to config.TICKER_UNIVERSE if today's scan hasn't run yet.
    Convenience alias used by dashboard and analyze_today_exits.
    """
    today_str = _et_now().strftime("%Y-%m-%d")
    try:
        daily = _read_daily_universe()
        if daily.get("date") == today_str and daily.get("universe"):
            return list(daily["universe"])
    except Exception:
        pass
    return list(TICKER_UNIVERSE)


def is_premarket_window() -> bool:
    """True during 09:00–09:29 ET."""
    et = _et_now()
    return _hm_in_range(et.hour, et.minute, PREMARKET_START_HM, PREMARKET_END_HM)


def is_scan_window() -> bool:
    """True during pre-market OR early session (09:00–11:30 ET)."""
    et = _et_now()
    return (
        _hm_in_range(et.hour, et.minute, PREMARKET_START_HM, PREMARKET_END_HM)
        or _hm_in_range(et.hour, et.minute, SESSION_START_HM, SESSION_END_HM)
    )


