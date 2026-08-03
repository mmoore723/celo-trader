#!/usr/bin/env python3
"""Convert downloaded Databento OPRA CBBO-1m files into V2 option quotes.

Example (run on the server after downloading data there). Start with a short
window; never normalize an entire multi-gigabyte archive just to answer the
first research question:
  python3 scripts/research_v2/import_databento_cbbo.py \
    --ticker TSLA --input-dir /data/databento/tsla \
    --start 2026-06-01 --end 2026-06-30 \
    --output research_data/TSLA_option_quotes_2026-06.csv
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from research_v2.providers import normalize_databento_cbbo_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Databento OPRA CBBO-1m CSV files")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", type=date.fromisoformat, help="Inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, help="Inclusive UTC date, YYYY-MM-DD")
    args = parser.parse_args()
    paths = sorted(args.input_dir.glob("*.csv*"))
    if not paths:
        raise SystemExit(f"No .csv or .csv.zst files found in {args.input_dir}")
    output = normalize_databento_cbbo_files(
        paths, args.ticker, args.output, start_date=args.start, end_date=args.end,
    )
    print(f"Wrote normalized {args.ticker.upper()} quotes to {output}")


if __name__ == "__main__":
    main()
