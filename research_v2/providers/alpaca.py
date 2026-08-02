"""Export authenticated Alpaca equity bars into a frozen V2 CSV artifact."""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
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


def _fetch_dated_bars(
    client: Any, symbol: str, start: date, end: date, timeframe: str, limit: int,
) -> list[dict[str, Any]]:
    """Request the declared interval directly and follow every API page.

    The ordinary live-client ``get_bars`` API accepts only a bar count. It is
    useful for trading, but unsuitable for research because it estimates the
    date window from *now*. V2 must instead name the exact source interval.
    """
    fetch = getattr(client, "_get", None)
    data_url = getattr(client, "data", None)
    if not callable(fetch) or not data_url:
        # Keeps this provider testable with a minimal fake and preserves a
        # compatibility fallback for older clients. Production V2 uses the
        # explicit-range path above.
        response = client.get_bars(symbol.upper(), timeframe, limit=limit)
        bars, is_error = response if isinstance(response, tuple) else (response, False)
        if is_error:
            raise RuntimeError(f"Alpaca returned an error while fetching {symbol}")
        return list(bars or [])

    params: dict[str, Any] = {
        "timeframe": timeframe,
        "start": datetime.combine(start, time.min, tzinfo=_ET).isoformat(),
        "end": datetime.combine(end, time.min, tzinfo=_ET).isoformat(),
        "limit": min(limit, 10_000),
        "adjustment": "split",
        "feed": "iex",
        "sort": "asc",
    }
    bars: list[dict[str, Any]] = []
    for _ in range(100):
        response = fetch(f"{data_url}/v2/stocks/{symbol.upper()}/bars", params)
        page = response.get("bars") or []
        bars.extend(page)
        token = response.get("next_page_token")
        if not token:
            return bars
        params = {**params, "page_token": token}
    raise RuntimeError("Alpaca pagination exceeded 100 pages; export aborted")


def _date_chunks(start: date, end: date, days: int | None) -> list[tuple[date, date]]:
    """Split a long request into exact, non-overlapping calendar intervals."""
    if days is None:
        return [(start, end)]
    if days < 1:
        raise ValueError("chunk_days must be positive when provided")
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        next_cursor = min(cursor + timedelta(days=days), end)
        chunks.append((cursor, next_cursor))
        cursor = next_cursor
    return chunks


def export_alpaca_csv(
    client: Any,
    symbol: str,
    start: date,
    end: date,
    output_path: str | Path,
    timeframe: str = "5Min",
    limit: int = 10_000,
    chunk_days: int | None = None,
    regular_session_only: bool = True,
    drop_partial_final_session: bool = True,
) -> Path:
    """Fetch, explicitly date-filter, and freeze Alpaca bars for V2 research.

    The broker call is made only at export time.  The simulator subsequently
    sees only the saved CSV and its SHA-256 fingerprint.
    """
    if not symbol or end <= start or limit < 1:
        raise ValueError("symbol, an increasing date range, and positive limit are required")
    bars: list[dict[str, Any]] = []
    for chunk_start, chunk_end in _date_chunks(start, end, chunk_days):
        bars.extend(_fetch_dated_bars(client, symbol, chunk_start, chunk_end, timeframe, limit))
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
    # A provider can repeat an inclusive interval boundary. Duplicate a
    # byte-identical bar safely; reject a conflicting revision instead of
    # silently inventing a history.
    unique_rows: list[dict[str, str | float]] = []
    for row in rows:
        if unique_rows and row["timestamp"] == unique_rows[-1]["timestamp"]:
            if row != unique_rows[-1]:
                raise ValueError(f"conflicting Alpaca bars at {row['timestamp']}")
            continue
        unique_rows.append(row)
    rows = unique_rows
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
