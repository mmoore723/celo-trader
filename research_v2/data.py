"""Reproducible bar datasets for V2 research.

The loader intentionally accepts a plain CSV first.  A broker-specific
adapter can export into this contract, but research runs should retain their
immutable input file hash instead of silently re-fetching revised data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from research_v2.models import Bar


@dataclass(frozen=True)
class BarDataset:
    source_path: str
    sha256: str
    bars: tuple[Bar, ...]

    @property
    def start(self) -> datetime:
        return self.bars[0].timestamp

    @property
    def end(self) -> datetime:
        return self.bars[-1].timestamp


def load_csv(path: str | Path) -> BarDataset:
    """Load chronological ``timestamp,open,high,low,close[,volume]`` bars.

    The source bytes are hashed before parsing, so a result can always name
    the exact data artifact on which it was produced.
    """
    file_path = Path(path)
    raw = file_path.read_bytes()
    digest = sha256(raw).hexdigest()
    rows: list[Bar] = []
    with file_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV must contain timestamp, open, high, low, and close columns")
        for row_number, row in enumerate(reader, start=2):
            try:
                text = str(row["timestamp"]).replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(text)
                rows.append(Bar(
                    timestamp=timestamp, open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid bar at CSV row {row_number}: {exc}") from exc
    if not rows:
        raise ValueError("CSV contains no bars")
    timestamps = [bar.timestamp for bar in rows]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("CSV bars must be strictly chronological with unique timestamps")
    return BarDataset(str(file_path), digest, tuple(rows))


def resample_regular_session(
    bars: tuple[Bar, ...], source_minutes: int, target_minutes: int,
) -> tuple[Bar, ...]:
    """Aggregate complete regular-session bars without crossing a session.

    The source timestamp labels a bar's opening time.  Every output bucket is
    anchored at 09:30 ET, so 15-minute bars are 09:30, 09:45, 10:00, and so
    on.  A bucket with a missing constituent bar is discarded rather than
    inventing an apparently complete candle from partial data.
    """
    if source_minutes < 1 or target_minutes < source_minutes or target_minutes % source_minutes:
        raise ValueError("target_minutes must be a whole multiple of source_minutes")
    if target_minutes == source_minutes:
        return bars
    expected = target_minutes // source_minutes
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        session_start = bar.timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed = int((bar.timestamp - session_start).total_seconds() // 60)
        if elapsed < 0:
            continue
        bucket_time = session_start + timedelta(minutes=(elapsed // target_minutes) * target_minutes)
        buckets.setdefault(bucket_time, []).append(bar)

    output: list[Bar] = []
    for bucket_time in sorted(buckets):
        group = buckets[bucket_time]
        expected_times = [bucket_time + timedelta(minutes=source_minutes * index) for index in range(expected)]
        if len(group) != expected or [bar.timestamp for bar in group] != expected_times:
            continue
        output.append(Bar(bucket_time, group[0].open, max(bar.high for bar in group),
                          min(bar.low for bar in group), group[-1].close,
                          sum(bar.volume for bar in group)))
    return tuple(output)
