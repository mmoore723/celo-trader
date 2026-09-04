"""Read-only CLI: audit existing paper fills without importing the trading runtime."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

from research.fill_fidelity import analyze


def audit(database: Path, account_id: str, start: str, end: str | None = None) -> dict:
    """Use one consistent SQLite snapshot and an explicit account and date window."""
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("An explicit account identity is required")
    start = date.fromisoformat(start).isoformat()
    if end is not None:
        end = date.fromisoformat(end).isoformat()
        if end <= start:
            raise ValueError("End date must be after start (end is exclusive)")
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        where = "t.paper=1 AND t.broker_account_id=? AND t.entry_time>=?"
        params = [account_id, start]
        if end is not None:
            where += " AND t.entry_time<?"
            params.append(end)
        trades = [dict(row) for row in conn.execute(
            "SELECT t.id,t.ticker,t.strategy_id,t.status,t.contracts,t.contract_symbol,"
            "t.entry_time,t.exit_time,t.entry_price,t.exit_price,t.realized_pnl "
            "FROM trades t WHERE " + where + " ORDER BY t.entry_time,t.id", params)]
        quotes = [dict(row) for row in conn.execute(
            "SELECT q.id,q.trade_id,q.contract_symbol,q.observed_at,q.observation_kind,"
            "q.bid,q.ask,q.source FROM option_quote_observations q "
            "JOIN trades t ON t.id=q.trade_id WHERE " + where + " ORDER BY q.id", params)]
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_database": str(database), "account_scoped": True,
            "start_inclusive": start, "end_exclusive": end, **analyze(trades, quotes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--account-id")
    identity.add_argument("--settings", type=Path, help="Read only active_broker_account_id; no credentials printed")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", help="Exclusive end date")
    args = parser.parse_args()
    try:
        account = args.account_id
        if args.settings is not None:
            account = json.loads(args.settings.read_text()).get("active_broker_account_id")
        result = audit(args.database, account, args.start, args.end)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Read-only audit failed: {type(exc).__name__}. Check path, schema, account and dates.\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
