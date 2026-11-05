"""Conservative weekday release guard, not an exchange holiday calendar."""
from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def market_hours(now: datetime) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Deployment clock must be timezone-aware")
    eastern = now.astimezone(ZoneInfo("America/New_York"))
    return eastern.weekday() < 5 and time(9, 30) <= eastern.time() < time(16)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-market-hours", action="store_true")
    args = parser.parse_args()
    if market_hours(datetime.now(timezone.utc)):
        if not args.force_market_hours:
            print("NOT DEPLOYED: normal releases are blocked weekdays 09:30-16:00 Eastern. "
                  "An explicitly authorized emergency release requires --force-market-hours.")
            return 1
        print("WARNING: explicit market-hours deployment override in use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
