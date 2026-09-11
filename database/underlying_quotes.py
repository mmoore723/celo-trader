"""Read-only evidence capture for intraminute underlying quotes."""
from __future__ import annotations

from datetime import datetime
import math
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
    if not all(math.isfinite(p) for p in (bid,ask)) or bid <= 0 or ask <= 0 or ask < bid:
        return False
    quote_at = None
    try:
        stamp = datetime.fromisoformat(str(quote.get('t') or '').replace('Z','+00:00'))
        if stamp.tzinfo is not None:
            quote_at = stamp.isoformat()
    except (TypeError,ValueError):
        pass  # Unknown exchange time stays missing, never becomes receive time.
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO underlying_quote_observations
               (broker_account_id,ticker,observed_at,bid,ask,mid,source,quote_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(broker_account_id or ""), ticker.strip().upper(),
             _to_et_isoformat(observed_at or datetime.now()), bid, ask,
             (bid + ask) / 2.0, source, quote_at),
        )
    return True
