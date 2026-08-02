"""Reproducible bar datasets for V2 research.

The loader intentionally accepts a plain CSV first.  A broker-specific
adapter can export into this contract, but research runs should retain their
immutable input file hash instead of silently re-fetching revised data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
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
