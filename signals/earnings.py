"""
signals/earnings.py — Earnings-blackout date check.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging

logger = logging.getLogger("celo_trader.signals")


def is_near_earnings(earnings_dates: list[str], blackout_days: int = 2) -> bool:
    """Return True if any earnings date falls within blackout_days of today."""
    from datetime import date
    today = date.today()
    for ed in earnings_dates:
        try:
            if abs((date.fromisoformat(ed) - today).days) <= blackout_days:
                logger.info("Earnings blackout: %s", ed)
                return True
        except ValueError:
            continue
    return False
