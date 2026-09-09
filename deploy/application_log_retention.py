#!/usr/bin/env python3
"""Apply the bounded retention policy to archived Celo bot logs."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path


DATED_LOG = re.compile(r"^bot\.log\.(\d{4}-\d{2}-\d{2})(?:\.gz)?$")
LEGACY_LOG = re.compile(r"^bot\.log\.\d+$")


def maintain_archived_logs(
    root: Path,
    retention_days: int = 14,
    *,
    today: date | None = None,
    dry_run: bool = False,
) -> dict:
    root = root.resolve()
    if not root.is_dir() or retention_days < 1:
        raise ValueError("log root must exist and retention_days must be at least 1")
    cutoff = (today or date.today()) - timedelta(days=retention_days)
    deleted: list[dict] = []
    compressed: list[dict] = []

    for path in sorted(root.iterdir()):
        if not path.is_file() or path.is_symlink() or path.name == "bot.log":
            continue
        match = DATED_LOG.fullmatch(path.name)
        expired = bool(match and date.fromisoformat(match.group(1)) < cutoff)
        if expired or LEGACY_LOG.fullmatch(path.name):
            size = path.stat().st_size
            deleted.append({"path": str(path), "bytes": size, "reason": "expired bot log"})
            if not dry_run:
                path.unlink()
            continue
        if match and path.suffix != ".gz":
            original_size = path.stat().st_size
            target = path.with_name(path.name + ".gz")
            if target.exists():
                raise RuntimeError(f"refusing to overwrite existing archive: {target}")
            if not dry_run:
                with path.open("rb") as source, gzip.open(target, "wb", compresslevel=6) as destination:
                    shutil.copyfileobj(source, destination)
                path.unlink()
                compressed_size = target.stat().st_size
            else:
                compressed_size = 0
            compressed.append({
                "source": str(path),
                "target": str(target),
                "original_bytes": original_size,
                "compressed_bytes": compressed_size,
            })

    return {
        "root": str(root),
        "dry_run": dry_run,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "deleted": deleted,
        "deleted_bytes": sum(item["bytes"] for item in deleted),
        "compressed": compressed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/opt/celo_trader/log"))
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(maintain_archived_logs(
        args.root,
        args.retention_days,
        dry_run=args.dry_run,
    ), indent=2))


if __name__ == "__main__":
    main()
