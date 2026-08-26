"""Observed-session exposure for ticker-aware qualification."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def load_ticker_exposure(db_paths: Iterable[Path]) -> dict[str, dict]:
    days: dict[str, set[str]] = {}
    for path in db_paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scanner_candle_observations'"
            ).fetchone()
            if not exists:
                continue
            for ticker, day in conn.execute(
                "SELECT ticker, substr(bar_time,1,10) FROM scanner_candle_observations GROUP BY 1,2"
            ):
                days.setdefault(str(ticker).upper(), set()).add(str(day))
        finally:
            conn.close()
    return {
        ticker: {
            "observed_sessions": len(values), "first_observed": min(values),
            "last_observed": max(values), "source": "scanner_candle_observations",
        }
        for ticker, values in days.items() if values
    }
