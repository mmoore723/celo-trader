"""
scanner/state_io.py — Disk persistence for the scanner's watchlist state
(scanner_state.json) and the daily universe (daily_universe.json).

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import json
import logging
from datetime import datetime

from scanner.constants import SCANNER_STATE, DAILY_UNIVERSE_PATH

logger = logging.getLogger("celo_trader.scanner")

# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_state(watchlist: list[str], scores: dict[str, float]) -> None:
    """Persist watchlist + scores to scanner_state.json for cross-process reads."""
    try:
        SCANNER_STATE.write_text(json.dumps({
            "written_utc": datetime.utcnow().isoformat(),
            "watchlist":   watchlist,
            "scores":      {t: round(s, 6) for t, s in scores.items() if s > 0},
        }, indent=2))
    except Exception as ex:
        logger.warning("Scanner state write failed: %s", ex)


def _write_daily_universe(
    date: str,
    universe: list[str],
    details: list[dict],
) -> None:
    """Write the day's scanned universe to daily_universe.json."""
    try:
        DAILY_UNIVERSE_PATH.write_text(json.dumps({
            "date":         date,
            "universe":     universe,
            "scan_details": details,
            "written_utc":  datetime.utcnow().isoformat(),
        }, indent=2))
    except Exception as ex:
        logger.warning("daily_universe.json write failed: %s", ex)


def _read_daily_universe() -> dict:
    """Read daily_universe.json; returns empty dict on any error."""
    try:
        if DAILY_UNIVERSE_PATH.exists():
            return json.loads(DAILY_UNIVERSE_PATH.read_text())
    except Exception as ex:
        logger.debug("_read_daily_universe: %s", ex)
    return {}
