"""Export authenticated Alpaca equity bars into a frozen V2 CSV artifact."""

from __future__ import annotations

import csv
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


_ET = ZoneInfo("America/New_York")


def _value(raw: dict[str, Any], short: str, long: str) -> Any:
    value = raw.get(short, raw.get(long))
    if value is None:
        raise ValueError(f"Alpaca bar missing {short}/{long}")
    return value


def _timestamp(value: Any) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("Alpaca bar timestamp must include a timezone")
    return parsed.astimezone(_ET)


def export_alpaca_csv(
    client: Any,
    symbol: str,
    start: date,
    end: date,
    output_path: str | Path,
    timeframe: str = "5Min",
    limit: int = 10_000,
    regular_session_only: bool = True,
    drop_partial_final_session: bool = True,
) -> Path:
    """Fetch, explicitly date-filter, and freeze Alpaca bars for V2 research.

    The broker call is made only at export time.  The simulator subsequently
    sees only the saved CSV and its SHA-256 fingerprint.
    """
    if not symbol or end <= start or limit < 1:
        raise ValueError("symbol, an increasing date range, and positive limit are required")
    response = client.get_bars(symbol.upper(), timeframe, limit=limit)
    bars, is_error = response if isinstance(response, tuple) else (response, False)
    if is_error:
        raise RuntimeError(f"Alpaca returned an error while fetching {symbol}")
    rows: list[dict[str, str | float]] = []
    for raw in bars or []:
        timestamp = _timestamp(_value(raw, "t", "time"))
        if not start <= timestamp.date() < end:
            continue
        if regular_session_only and not (time(9, 30) <= timestamp.time() < time(16, 0)):
            continue
        rows.append({
            "timestamp": timestamp.isoformat(),
            "open": float(_value(raw, "o", "open")),
            "high": float(_value(raw, "h", "high")),
            "low": float(_value(raw, "l", "low")),
            "close": float(_value(raw, "c", "close")),
            "volume": float(raw.get("v", raw.get("volume", 0.0))),
        })
    rows.sort(key=lambda row: str(row["timestamp"]))
    # A live or interrupted final session is not a valid historical close.  It
    # can fabricate an end-of-data exit and materially distort a strategy.
    # Drop it unless its last regular-session bar reaches the expected 15:55
    # close for a 5-minute feed.  Earlier sessions stay intact.
    if regular_session_only and drop_partial_final_session and rows:
        latest = datetime.fromisoformat(str(rows[-1]["timestamp"]))
        if latest.time() < time(15, 55):
            last_date = latest.date()
            rows = [row for row in rows if datetime.fromisoformat(str(row["timestamp"])).date() != last_date]
    if not rows:
        raise ValueError(f"Alpaca returned no {timeframe} bars for {symbol} {start} to {end}")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    return destination
