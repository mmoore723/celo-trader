"""Paper-trade option quote observations used for execution-fidelity research.

These writes are strictly observational.  They never change a trade, a risk
limit, a broker order, or a live position.  A database issue is intentionally
non-fatal: recording evidence must not interfere with an already-confirmed
paper trade or its protective exit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
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


def record_candidate_option_quote(
    *, candidate_id: str, contract_symbol: str, observation_kind: str,
    observed_at: datetime, quote: Mapping[str, Any] | None, source: str,
) -> bool:
    """Store an executable quote for a scanner candidate, never an order."""
    allowed = {"entry", "mark_30m", "mark_60m", "mark_90m"}
    if observation_kind not in allowed:
        raise ValueError(f"observation_kind must be one of {sorted(allowed)}")
    if not candidate_id or not contract_symbol:
        return False
    quote = quote or {}
    bid, ask, mid = (_number(quote.get(key)) for key in ("bid", "ask", "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 6)
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO candidate_option_quote_observations
                   (candidate_id, observed_at, observation_kind, contract_symbol,
                    bid, ask, mid, last, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (candidate_id, _to_et_isoformat(observed_at), observation_kind,
                 contract_symbol, bid, ask, mid, _number(quote.get("last")), source),
            )
        return bool(cursor.rowcount)
    except Exception:
        logger.warning("candidate option quote capture failed candidate=%s kind=%s",
                       candidate_id, observation_kind, exc_info=True)
        return False


def capture_due_candidate_option_quotes(
    *, ticker: str, observed_at: datetime, quote_lookup,
    broker_account_id: str | None = None,
) -> int:
    """Capture due 30/60/90-minute bid/ask marks for today's candidates.

    The supplied callback only reads a quote. This function has no broker
    order method and its table has no quantity/order fields by design.
    """
    horizons = (("mark_30m", 30), ("mark_60m", 60), ("mark_90m", 90))
    clauses = ["s.ticker = ?", "substr(s.observed_at, 1, 10) = ?",
               "q.observation_kind = 'entry'"]
    params: list[Any] = [ticker.upper(), observed_at.date().isoformat()]
    if broker_account_id:
        clauses.append("s.broker_account_id = ?")
        params.append(broker_account_id)
    captured = 0
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT s.candidate_id, s.observed_at, q.contract_symbol
                   FROM shadow_candidates s
                   JOIN candidate_option_quote_observations q
                     ON q.candidate_id = s.candidate_id
                   WHERE """ + " AND ".join(clauses), tuple(params),
            ).fetchall()
            for row in rows:
                started = datetime.fromisoformat(str(row["observed_at"]))
                for kind, minutes in horizons:
                    if observed_at < started + timedelta(minutes=minutes):
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM candidate_option_quote_observations WHERE candidate_id=? AND observation_kind=?",
                        (row["candidate_id"], kind),
                    ).fetchone()
                    if exists:
                        continue
                    quote = quote_lookup(row["contract_symbol"])
                    if quote and record_candidate_option_quote(
                        candidate_id=row["candidate_id"], contract_symbol=row["contract_symbol"],
                        observation_kind=kind, observed_at=observed_at, quote=quote,
                        source="tradier_candidate_followup",
                    ):
                        captured += 1
        return captured
    except Exception:
        logger.warning("candidate due quote sweep failed for %s", ticker, exc_info=True)
        return captured
