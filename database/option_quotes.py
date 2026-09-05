"""Paper-trade option quote observations used for execution-fidelity research.

These writes are strictly observational.  They never change a trade, a risk
limit, a broker order, or a live position.  A database issue is intentionally
non-fatal: recording evidence must not interfere with an already-confirmed
paper trade or its protective exit.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from database.connection import get_conn
from database.helpers import _to_et_isoformat

logger = logging.getLogger("celo_trader.database")

# A fixed-horizon mark must be captured close to that horizon. A quote first
# seen after a restart much later in the day is real, but it is not a truthful
# 30/60/90/120-minute result and must remain absent from that bucket.
CANDIDATE_MARK_GRACE_MINUTES = 5
CANDIDATE_MARK_HORIZONS = (30, 60, 90, 120)
CANDIDATE_OBSERVATION_KINDS = frozenset({
    "entry", *(f"mark_{minutes}m" for minutes in CANDIDATE_MARK_HORIZONS),
})


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
    if observation_kind not in CANDIDATE_OBSERVATION_KINDS:
        raise ValueError(
            "observation_kind must be one of "
            f"{sorted(CANDIDATE_OBSERVATION_KINDS)}"
        )
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


def promote_candidate_entry_quote(
    *, candidate_id: str, contract_symbol: str, observed_at: datetime,
    quote: Mapping[str, Any] | None, source: str,
) -> bool:
    """Make the final executable contract the candidate's primary entry quote.

    A candidate can be priced before every entry gate clears.  The final
    selector is allowed to choose a different contract after that preview.  In
    that case, preserve the preview in the alternatives table and replace the
    single primary ``entry`` row with the exact contract carried by the order
    intent.  This function is observational and must never place or alter an
    order.
    """
    if not candidate_id or not contract_symbol:
        return False
    quote = quote or {}
    bid, ask, mid = (_number(quote.get(key)) for key in ("bid", "ask", "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 6)
    observed_iso = _to_et_isoformat(observed_at)
    try:
        with get_conn() as conn:
            prior = conn.execute(
                """SELECT contract_symbol, observed_at, bid, ask, mid, source
                   FROM candidate_option_quote_observations
                   WHERE candidate_id = ? AND observation_kind = 'entry'""",
                (candidate_id,),
            ).fetchone()
            if prior is not None and str(prior[0]) != contract_symbol:
                conn.execute(
                    """INSERT OR IGNORE INTO candidate_contract_alternatives
                       (candidate_id, contract_symbol, observed_at,
                        observation_kind, bid, ask, mid, policy_json, source)
                       VALUES (?, ?, ?, 'entry', ?, ?, ?, ?, ?)""",
                    (
                        candidate_id, str(prior[0]), str(prior[1]), prior[2],
                        prior[3], prior[4],
                        json.dumps(["preview_superseded_by_order_intent"]),
                        str(prior[5] or "tradier_contract_preview"),
                    ),
                )
            conn.execute(
                """INSERT INTO candidate_option_quote_observations
                   (candidate_id, observed_at, observation_kind, contract_symbol,
                    bid, ask, mid, last, source)
                   VALUES (?, ?, 'entry', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_id, observation_kind) DO UPDATE SET
                       observed_at = excluded.observed_at,
                       contract_symbol = excluded.contract_symbol,
                       bid = excluded.bid,
                       ask = excluded.ask,
                       mid = excluded.mid,
                       last = excluded.last,
                       source = excluded.source""",
                (
                    candidate_id, observed_iso, contract_symbol, bid, ask, mid,
                    _number(quote.get("last")), source,
                ),
            )
        return True
    except Exception:
        logger.warning(
            "authoritative candidate quote promotion failed candidate=%s symbol=%s",
            candidate_id, contract_symbol, exc_info=True,
        )
        return False


def record_candidate_contract_alternative(
    *, candidate_id: str, contract: Mapping[str, Any], observation_kind: str,
    observed_at: datetime, policies: list[str] | None = None,
    source: str = "reviewed_selector_shadow",
) -> bool:
    """Persist one non-executing contract-policy observation."""
    if observation_kind not in CANDIDATE_OBSERVATION_KINDS:
        raise ValueError(
            "observation_kind must be one of "
            f"{sorted(CANDIDATE_OBSERVATION_KINDS)}"
        )
    symbol = str(contract.get("symbol") or contract.get("contract_symbol") or "")
    if not candidate_id or not symbol:
        return False
    bid, ask, mid = (_number(contract.get(key)) for key in ("bid", "ask", "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 6)
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO candidate_contract_alternatives
                   (candidate_id, contract_symbol, observed_at, observation_kind,
                    bid, ask, mid, policy_json, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (candidate_id, symbol, _to_et_isoformat(observed_at), observation_kind,
                 bid, ask, mid, json.dumps(policies or []), source),
            )
        return bool(cursor.rowcount)
    except Exception:
        logger.warning("candidate alternative quote capture failed candidate=%s symbol=%s",
                       candidate_id, symbol, exc_info=True)
        return False
def capture_due_candidate_option_quotes(
    *, ticker: str, observed_at: datetime, quote_lookup,
    broker_account_id: str | None = None,
) -> int:
    """Capture due 30/60/90/120-minute bid/ask marks for today's candidates.

    The supplied callback only reads a quote. This function has no broker
    order method and its table has no quantity/order fields by design.
    """
    horizons = tuple(
        (f"mark_{minutes}m", minutes) for minutes in CANDIDATE_MARK_HORIZONS
    )
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
                    due_at = started + timedelta(minutes=minutes)
                    if observed_at < due_at:
                        continue
                    if observed_at > due_at + timedelta(minutes=CANDIDATE_MARK_GRACE_MINUTES):
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
        # Measure every declared policy winner against the same horizons. The
        # table is deliberately separate from the primary selected contract,
        # so these rows can never be mistaken for an order or trade.
        with get_conn() as conn:
            alt_rows = conn.execute(
                """SELECT DISTINCT a.candidate_id, s.observed_at, a.contract_symbol,
                                  a.policy_json
                   FROM candidate_contract_alternatives a
                   JOIN shadow_candidates s ON s.candidate_id = a.candidate_id
                   WHERE s.ticker = ? AND substr(s.observed_at, 1, 10) = ?
                     AND a.observation_kind = 'entry'"""
                + (" AND s.broker_account_id = ?" if broker_account_id else ""),
                tuple([ticker.upper(), observed_at.date().isoformat()] + ([broker_account_id] if broker_account_id else [])),
            ).fetchall()
        for row in alt_rows:
            started = datetime.fromisoformat(str(row["observed_at"]))
            for kind, minutes in horizons:
                due_at = started + timedelta(minutes=minutes)
                if observed_at < due_at:
                    continue
                if observed_at > due_at + timedelta(minutes=CANDIDATE_MARK_GRACE_MINUTES):
                    continue
                with get_conn() as conn:
                    exists = conn.execute(
                        """SELECT 1 FROM candidate_contract_alternatives
                           WHERE candidate_id=? AND contract_symbol=? AND observation_kind=?""",
                        (row["candidate_id"], row["contract_symbol"], kind),
                    ).fetchone()
                if exists:
                    continue
                quote = quote_lookup(row["contract_symbol"])
                if quote and record_candidate_contract_alternative(
                    candidate_id=row["candidate_id"], contract={**dict(quote), "symbol": row["contract_symbol"]},
                    observation_kind=kind, observed_at=observed_at,
                    policies=json.loads(row["policy_json"] or "[]"), source="tradier_alternative_followup",
                ):
                    captured += 1
        return captured
    except Exception:
        logger.warning("candidate due quote sweep failed for %s", ticker, exc_info=True)
        return captured
