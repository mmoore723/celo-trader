"""Validate an externally sourced strategy manifest and optional Pine source."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.candidates import hash_source, load_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pine-source", help="saved Pine source to hash and compare")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.pine_source:
        observed = hash_source(args.pine_source)
        if observed != manifest.source_sha256:
            raise SystemExit("source hash mismatch: manifest does not describe this Pine source")
    print(f"valid candidate manifest: {manifest.candidate_id}")


if __name__ == "__main__":
    main()
