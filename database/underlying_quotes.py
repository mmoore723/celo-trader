"""Read-only evidence capture for intraminute underlying quotes."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from database.connection import get_conn
from database.helpers import _to_et_isoformat


def record_underlying_quote(
    ticker: str, quote: Mapping[str, object] | None, *,
    broker_account_id: str | None = None, observed_at: datetime | None = None,
    source: str = "alpaca",
) -> bool:
    """Persist an executable bid/ask midpoint without affecting decisions."""
    if not quote:
        return False
    try:
        bid, ask = float(quote.get("bp", 0) or 0), float(quote.get("ap", 0) or 0)
    except (TypeError, ValueError):
        return False
    if bid <= 0 or ask <= 0 or ask < bid:
        return False
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO underlying_quote_observations
               (broker_account_id,ticker,observed_at,bid,ask,mid,source)
               VALUES (?,?,?,?,?,?,?)""",
            (str(broker_account_id or ""), ticker.strip().upper(),
             _to_et_isoformat(observed_at or datetime.now()), bid, ask,
             (bid + ask) / 2.0, source),
        )
    return True
