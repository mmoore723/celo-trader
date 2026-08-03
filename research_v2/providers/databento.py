"""Streaming importer for Databento OPRA ``cbbo-1m`` CSV downloads.

The importer is deliberately offline and research-only. It converts the
provider export into the V2 option-quote contract, uses ask for a hypothetical
buy and bid for a hypothetical sell later, and never touches broker clients.
"""
from __future__ import annotations

import csv
import io
import re
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, TextIO


_OCC = re.compile(r"^\s*([A-Z.]+)\s*(\d{6})([CP])(\d{8})\s*$")
_PRICE_COLUMNS = (
    ("bid_px_00", "ask_px_00"),  # Databento CBBO/CMBP CSV export
    ("bid", "ask"),               # normalized/test fixture input
)


@contextmanager
def _open_csv(path: Path) -> Iterator[TextIO]:
    """Open plain CSV or a zstd-compressed Databento CSV as text."""
    if path.suffix.lower() != ".zst":
        with path.open("r", encoding="utf-8", newline="") as handle:
            yield handle
        return
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError("Install zstandard to import .csv.zst Databento files") from exc
    with path.open("rb") as raw:
        with zstd.ZstdDecompressor().stream_reader(raw) as reader:
            with io.TextIOWrapper(reader, encoding="utf-8", newline="") as handle:
                yield handle


def _parse_symbol(raw_symbol: object, expected_ticker: str) -> tuple[str, str, str, float, str] | None:
    """Parse OCC/OSI raw option symbol into generic quote identity fields."""
    match = _OCC.match(str(raw_symbol or ""))
    if not match:
        return None
    underlying, yymmdd, call_put, strike_raw = match.groups()
    underlying = underlying.upper()
    if underlying != expected_ticker:
        return None
    expiry = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:]}"
    option_type = "call" if call_put == "C" else "put"
    strike = float(strike_raw) / 1000.0
    return str(raw_symbol).strip(), underlying, expiry, strike, option_type


def _timestamp(row: dict[str, str]) -> str:
    value = row.get("ts_event") or row.get("ts_recv") or row.get("timestamp")
    if not value:
        raise ValueError("Databento row has no ts_event, ts_recv, or timestamp")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Databento timestamp must include timezone")
    return parsed.isoformat()


def _prices(row: dict[str, str]) -> tuple[float, float] | None:
    for bid_key, ask_key in _PRICE_COLUMNS:
        if row.get(bid_key) in {None, ""} or row.get(ask_key) in {None, ""}:
            continue
        try:
            bid, ask = float(row[bid_key]), float(row[ask_key])
        except ValueError:
            continue
        # Zero/negative values and Databento's empty-book sentinel are not
        # executable quotes. Drop them rather than invent a fill.
        if bid > 0 and ask >= bid and ask < 1_000_000:
            return bid, ask
    return None


def normalize_databento_cbbo_files(
    paths: Iterable[str | Path], ticker: str, output_path: str | Path,
    start_date: date | None = None, end_date: date | None = None,
) -> Path:
    """Stream selected OPRA CBBO-1m files into V2's normalized quote CSV.

    Only the requested underlying and optional inclusive date window are
    retained, so a large provider download becomes a compact, immutable
    research artifact. Rows remain chronological; duplicate timestamp/symbol
    records keep the last quote from that source minute, which is the
    conservative usable quote at that instant.
    """
    expected_ticker = ticker.upper().strip()
    if not expected_ticker:
        raise ValueError("ticker is required")
    if start_date and end_date and end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    last_timestamp: str | None = None
    last_key: tuple[str, str] | None = None
    with destination.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=[
            "timestamp", "option_symbol", "underlying", "expiration", "strike", "option_type", "bid", "ask",
        ])
        writer.writeheader()
        for raw_path in sorted((Path(path) for path in paths), key=lambda path: path.name):
            with _open_csv(raw_path) as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "symbol" not in reader.fieldnames:
                    raise ValueError(f"{raw_path.name} is missing Databento symbol column")
                for row in reader:
                    identity = _parse_symbol(row.get("symbol"), expected_ticker)
                    prices = _prices(row)
                    if identity is None or prices is None:
                        continue
                    option_symbol, underlying, expiration, strike, option_type = identity
                    timestamp = _timestamp(row)
                    timestamp_date = datetime.fromisoformat(timestamp).date()
                    if start_date and timestamp_date < start_date:
                        continue
                    if end_date and timestamp_date > end_date:
                        continue
                    key = (timestamp, option_symbol)
                    if last_timestamp is not None and timestamp < last_timestamp:
                        raise ValueError(f"{raw_path.name} is not chronological at {timestamp}")
                    # Databento CBBO-1m should provide one observation per
                    # symbol/minute. An exact repeat contributes no evidence.
                    if key == last_key:
                        continue
                    last_timestamp = timestamp
                    last_key = key
                    writer.writerow({
                        "timestamp": timestamp, "option_symbol": option_symbol,
                        "underlying": underlying, "expiration": expiration,
                        "strike": f"{strike:.3f}", "option_type": option_type,
                        "bid": f"{prices[0]:.6f}", "ask": f"{prices[1]:.6f}",
                    })
                    written += 1
    if not written:
        destination.unlink(missing_ok=True)
        raise ValueError(f"No valid {expected_ticker} CBBO quotes found")
    return destination
