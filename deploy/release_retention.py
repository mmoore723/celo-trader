#!/usr/bin/env python3
"""Safely remove stale Celo deployment artifacts after a healthy release.

Only Celo-created staging and rollback directories directly below the supplied
root are eligible. The active checkout and all application data live outside
that root and are therefore out of scope.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Removal:
    path: str
    bytes: int
    reason: str


def _directory_bytes(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    )


def _is_usable_rollback(path: Path) -> bool:
    archive = path / "source.tar.gz"
    if path.name.endswith(".failed") or not archive.is_file():
        return False
    try:
        return tarfile.is_tarfile(archive)
    except OSError:
        return False


def cleanup_release_artifacts(root: Path, keep: int = 2, *, dry_run: bool = False) -> dict:
    """Keep the newest usable rollbacks and remove older Celo leftovers."""
    root = root.resolve()
    if not root.is_dir() or keep < 1:
        raise ValueError("retention root must exist and keep must be at least 1")

    entries = [item for item in root.iterdir() if item.is_dir() and not item.is_symlink()]
    stages = [item for item in entries if item.name.startswith("celo-") and "-stage." in item.name]
    rollbacks = [item for item in entries if item.name.startswith("celo-") and "-rollback." in item.name]
    usable = sorted(
        (item for item in rollbacks if _is_usable_rollback(item)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    retained = usable[:keep]
    retained_set = set(retained)

    targets: list[tuple[Path, str]] = [(item, "staging leftover") for item in stages]
    for item in rollbacks:
        if item in retained_set:
            continue
        reason = "failed rollback leftover" if item.name.endswith(".failed") else "older rollback"
        targets.append((item, reason))

    removals: list[Removal] = []
    for path, reason in sorted(targets, key=lambda pair: pair[0].name):
        if path.parent.resolve() != root or path.is_symlink():
            raise RuntimeError(f"refusing unsafe target: {path}")
        size = _directory_bytes(path)
        removals.append(Removal(str(path), size, reason))
        if not dry_run:
            shutil.rmtree(path)

    return {
        "root": str(root),
        "dry_run": dry_run,
        "keep": keep,
        "retained": [str(path) for path in retained],
        "removed": [asdict(item) for item in removals],
        "removed_bytes": sum(item.bytes for item in removals),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/var/tmp"))
    parser.add_argument("--keep", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(cleanup_release_artifacts(args.root, args.keep, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
