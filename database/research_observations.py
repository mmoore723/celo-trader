"""Durable quote-to-quote evidence for isolated paper research studies.

Unlike ``trades``, this module has no quantity, broker order, fill, position,
or P&L field.  It only records what could have been bought at the displayed
ask and later sold at the displayed bid.  The entry pipeline never imports
this module.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Mapping

from database.connection import get_conn
from database.helpers import _to_et_isoformat

logger = logging.getLogger("celo_trader.database")


def _price(quote: Mapping[str, Any] | None, key: str) -> float | None:
    try:
        value = float((quote or {}).get(key))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def start_paper_research_observation(
    *, study_id: str, observed_at: datetime, ticker: str, direction: str,
    underlying_entry_price: float, contract: Mapping[str, Any] | None,
    broker_account_id: str | None, metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Create one non-ordering observation for the current ET calendar date.

    Returns False when an observation for this study/account/day already
    exists.  That makes a fast polling loop unable to duplicate a study.
    """
    if not study_id or direction not in {"bullish", "bearish"}:
        return False
    timestamp = _to_et_isoformat(observed_at)
    account_key = broker_account_id or ""
    contract = contract or {}
    bid, ask = _price(contract, "bid"), _price(contract, "ask")
    mid = _price(contract, "mid")
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 6)
    try:
        entry = float(underlying_entry_price)
    except (TypeError, ValueError):
        return False
    if entry <= 0:
        return False
    # Keep a missing-contract row open too: it still gives us the underlying
    # outcome and makes availability itself measurable at the close window.
    status = "open"
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO paper_research_option_observations
                   (study_id, observation_date, status, created_at, ticker, direction,
                    trigger_bar, broker_account_id, underlying_entry_price,
                    contract_symbol, expiry, strike, entry_bid, entry_ask, entry_mid,
                    metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    study_id, timestamp[:10], status, timestamp, ticker.upper(), direction,
                    timestamp, account_key, entry, contract.get("symbol"),
                    contract.get("expiry"), _price(contract, "strike"), bid, ask, mid,
                    json.dumps(dict(metadata or {}), default=str, sort_keys=True),
                ),
            )
        return True
    except Exception:
        logger.warning("paper research observation start failed", exc_info=True)
        return False


def close_due_paper_research_observations(
    *, study_id: str, observed_at: datetime, ticker: str, underlying_exit_price: float,
    broker_account_id: str | None, quote_lookup: Callable[[str], Mapping[str, Any] | None],
) -> int:
    """Close today's open rows using conservative exit bid; never raises."""
    timestamp = _to_et_isoformat(observed_at)
    account_key = broker_account_id or ""
    try:
        exit_underlying = float(underlying_exit_price)
    except (TypeError, ValueError):
        return 0
    if exit_underlying <= 0:
        return 0
    clauses = ["study_id = ?", "ticker = ?", "status = 'open'", "observation_date = ?"]
    params: list[Any] = [study_id, ticker.upper(), timestamp[:10]]
    clauses.append("broker_account_id = ?")
    params.append(account_key)
    closed = 0
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, direction, underlying_entry_price, contract_symbol, entry_ask "
                "FROM paper_research_option_observations WHERE " + " AND ".join(clauses), tuple(params),
            ).fetchall()
            for row in rows:
                quote = quote_lookup(str(row["contract_symbol"])) if row["contract_symbol"] else None
                exit_bid, exit_ask = _price(quote, "bid"), _price(quote, "ask")
                exit_mid = _price(quote, "mid")
                if exit_mid is None and exit_bid is not None and exit_ask is not None:
                    exit_mid = round((exit_bid + exit_ask) / 2, 6)
                entry = float(row["underlying_entry_price"] or 0)
                raw_move = (exit_underlying - entry) / entry * 100 if entry > 0 else None
                directional = raw_move if row["direction"] == "bullish" else -raw_move if raw_move is not None else None
                entry_ask = float(row["entry_ask"] or 0)
                executable = ((exit_bid - entry_ask) / entry_ask * 100
                              if entry_ask > 0 and exit_bid is not None else None)
                conn.execute(
                    """UPDATE paper_research_option_observations
                       SET status = 'closed', closed_at = ?, underlying_exit_price = ?,
                           underlying_move_pct = ?, exit_bid = ?, exit_ask = ?, exit_mid = ?,
                           executable_return_pct = ?
                       WHERE id = ? AND status = 'open'""",
                    (timestamp, exit_underlying, directional, exit_bid, exit_ask, exit_mid, executable, row["id"]),
                )
                closed += 1
        return closed
    except Exception:
        logger.warning("paper research observation close failed", exc_info=True)
        return 0


def get_paper_research_scorecard(*, study_id: str, broker_account_id: str | None) -> dict[str, Any]:
    """Return read-only evidence; it is intentionally not an allocation input."""
    clauses = ["study_id = ?"]
    params: list[Any] = [study_id]
    clauses.append("broker_account_id = ?")
    params.append(broker_account_id or "")
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS observations,
                      SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                      SUM(CASE WHEN contract_symbol IS NULL OR contract_symbol = '' THEN 1 ELSE 0 END) AS unavailable,
                      AVG(underlying_move_pct) AS avg_underlying_move_pct,
                      AVG(executable_return_pct) AS avg_executable_return_pct,
                      SUM(CASE WHEN executable_return_pct > 0 THEN 1 ELSE 0 END) AS option_wins,
                      SUM(CASE WHEN executable_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS quote_measured
               FROM paper_research_option_observations WHERE """ + " AND ".join(clauses), tuple(params),
        ).fetchone()
    measured = int(row["quote_measured"] or 0)
    return {
        "study_id": study_id, "observations": int(row["observations"] or 0),
        "closed": int(row["closed"] or 0), "unavailable": int(row["unavailable"] or 0),
        "quote_measured": measured,
        "option_win_rate_pct": round(int(row["option_wins"] or 0) * 100 / measured, 1) if measured else None,
        "avg_underlying_move_pct": round(float(row["avg_underlying_move_pct"]), 4) if row["avg_underlying_move_pct"] is not None else None,
        "avg_executable_return_pct": round(float(row["avg_executable_return_pct"]), 4) if row["avg_executable_return_pct"] is not None else None,
    }
