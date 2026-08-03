"""Paper-trade option quote observations used for execution-fidelity research.

These writes are strictly observational.  They never change a trade, a risk
limit, a broker order, or a live position.  A database issue is intentionally
non-fatal: recording evidence must not interfere with an already-confirmed
paper trade or its protective exit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping, Optional

from database.connection import get_conn
from database.helpers import _to_et_isoformat

logger = logging.getLogger("celo_trader.database")


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def record_paper_option_quote(
    *,
    trade_id: int,
    contract_symbol: str,
    observation_kind: str,
    observed_at: datetime,
    quote: Mapping[str, Any] | None,
    source: str,
    fill_price: float | None = None,
) -> bool:
    """Persist one entry/mark/exit quote for a paper trade.

    ``mark`` rows are kept at most once per trade per minute.  ``entry`` and
    ``exit`` have independent rows even when both happen in the same minute.
    Returns ``False`` instead of raising so capture cannot affect trading.
    """
    if observation_kind not in {"entry", "mark", "exit"}:
        raise ValueError("observation_kind must be entry, mark, or exit")
    if not contract_symbol:
        return False

    quote = quote or {}
    observed_iso = _to_et_isoformat(observed_at)
    minute_key = observed_iso[:16]
    bid = _number(quote.get("bid"))
    ask = _number(quote.get("ask"))
    mid = _number(quote.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 6)

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO option_quote_observations
                    (trade_id, observed_at, observed_minute, observation_kind,
                     contract_symbol, bid, ask, mid, last, fill_price, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id, observed_iso, minute_key, observation_kind,
                    contract_symbol, bid, ask, mid, _number(quote.get("last")),
                    _number(fill_price), source,
                ),
            )
        return True
    except Exception:
        logger.warning(
            "paper option quote capture failed for trade=%s kind=%s",
            trade_id, observation_kind, exc_info=True,
        )
        return False
