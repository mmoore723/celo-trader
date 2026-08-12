"""Immutable candidate specifications for externally sourced strategies."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str
    source_url: str
    source_sha256: str
    symbol: str
    timeframe: str
    session: str
    commission_note: str
    slippage_note: str
    bar_magnifier: bool
    calc_on_every_tick: bool
    process_orders_on_close: bool


def load_manifest(path: str | Path) -> CandidateManifest:
    """Load a self-contained, reviewable candidate specification JSON."""
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    required = {
        "candidate_id", "source_url", "source_sha256", "symbol", "timeframe", "session",
        "commission_note", "slippage_note", "bar_magnifier", "calc_on_every_tick", "process_orders_on_close",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"candidate manifest missing: {', '.join(missing)}")
    source_hash = str(payload["source_sha256"])
    if len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash.lower()):
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    return CandidateManifest(**{key: payload[key] for key in required})


def hash_source(path: str | Path) -> str:
    """Fingerprint the exact locally saved Pine source reviewed for a candidate."""
    return sha256(Path(path).read_bytes()).hexdigest()
