"""Export a short, explicit yfinance window into a fingerprintable V2 CSV.

This exporter is intentionally separate from the simulator.  It must be run
once while online, then V2 research reads the saved bytes offline.  Yahoo's
intraday limits mean this is convenience data for screening, not a substitute
for historical options quotes or an institutional data feed.
"""

from __future__ import annotations

import concurrent.futures
import csv
from datetime import date
from pathlib import Path


def export_yfinance_csv(
    symbol: str,
    start: date,
    end: date,
    output_path: str | Path,
    interval: str = "5m",
    timeout_seconds: int = 30,
) -> Path:
    """Download a bounded intraday slice and write canonical V2 OHLCV CSV.

    The explicit range and output file make the download a research artifact,
    not an opaque provider call inside a backtest.  A timeout prevents an
    unavailable provider from trapping a research run indefinitely.
    """
    if not symbol or end <= start:
        raise ValueError("symbol is required and end must be after start")
    if interval in {"1m", "2m", "5m", "15m", "30m", "60m", "90m"} and (end - start).days > 59:
        raise ValueError("intraday yfinance export is limited to 59 calendar days per artifact")
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required only to export a V2 source CSV") from exc

    def _download():
        return yf.download(
            symbol.upper(), start=start.isoformat(), end=end.isoformat(),
            interval=interval, auto_adjust=True, progress=False,
        )

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_download)
    try:
        raw = future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"yfinance did not return {symbol} within {timeout_seconds}s") from exc
    finally:
        executor.shutdown(wait=False)
    if raw is None or raw.empty:
        raise ValueError(f"no {interval} bars returned for {symbol} {start} to {end}")
    if hasattr(raw.columns, "get_level_values"):
        raw.columns = raw.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(raw.columns)):
        raise ValueError("provider data is missing OHLC columns")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for timestamp, row in raw.iterrows():
            writer.writerow({
                "timestamp": timestamp.isoformat(),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0.0)),
            })
    return destination
