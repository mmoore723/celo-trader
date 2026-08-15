"""Small, process-local atomic file helpers for mutable runtime state.

All writers use a sibling temporary file followed by ``os.replace`` so a
reader can never observe a truncated JSON document.  The per-path lock also
keeps read/modify/write updates from losing fields when two bot threads update
the same user's dashboard snapshot at once.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable


_locks_guard = threading.Lock()
_path_locks: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _locks_guard:
        return _path_locks.setdefault(key, threading.RLock())


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """Durably replace ``path`` with ``text`` without exposing partial data."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(text)
                temporary.flush()
                os.fsync(temporary.fileno())
            if mode is not None:
                os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        Path(path), json.dumps(payload, indent=2, default=str) + "\n",
    )


def atomic_update_json(
    path: Path,
    update: Callable[[dict], dict | None],
    *,
    default: dict | None = None,
) -> dict:
    """Lock, read, mutate and atomically replace one JSON object."""
    path = Path(path)
    with _lock_for(path):
        current = dict(default or {})
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current.update(loaded)
            except (OSError, json.JSONDecodeError):
                # The new snapshot remains usable even if it is repairing a
                # legacy truncated file from before atomic writes existed.
                pass
        replacement = update(current)
        result = current if replacement is None else replacement
        if not isinstance(result, dict):
            raise TypeError("atomic_update_json callback must return a dict or None")
        atomic_write_json(path, result)
        return result
