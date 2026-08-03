"""Paper-only candidate ledger for measuring router gates honestly.

It records raw strategy signals before the router's quality gates and links
their later journal outcome.  It is deliberately observational: it never
requests contracts, sends orders, or participates in position management.
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

from database import get_conn, _now_et

logger = logging.getLogger("celo_trader.shadow_ledger")


def record_router_candidate(ticker: str, signal: object) -> None:
    """Persist a raw paper candidate and attach its opaque id to the signal."""
    try:
        from config import get_settings
        meta = getattr(signal, "meta", None)
        if not isinstance(meta, dict):
            meta = {}
            setattr(signal, "meta", meta)
        if meta.get("shadow_candidate_id"):
            return
        candidate_id = uuid4().hex
        observed_at = _now_et().isoformat()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO shadow_candidates
                   (candidate_id, observed_at, ticker, strategy_id, direction,
                    confidence, trigger_bar, tier, broker_account_id, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id, observed_at, ticker.upper(), str(getattr(signal, "strategy_id", "UNKNOWN")),
                    str(getattr(signal, "direction", "unknown")), float(getattr(signal, "confidence", 0.0)),
                    str(getattr(signal, "trigger_bar", "")), str(getattr(signal, "tier", "main")),
                    get_settings().get("active_broker_account_id") or None,
                    json.dumps(meta, default=str, sort_keys=True),
                ),
            )
        meta["shadow_candidate_id"] = candidate_id
    except Exception:
        logger.warning("shadow candidate write failed (non-fatal)", exc_info=True)


def resolve_candidate_from_context(
    context: dict | None, outcome: str, reason_code: str | None,
    reason_detail: str | None, trade_id: int | None,
) -> None:
    """Attach the final router/entry decision to its previously recorded candidate."""
    try:
        meta = (context or {}).get("strategy_meta") if isinstance(context, dict) else None
        candidate_id = meta.get("shadow_candidate_id") if isinstance(meta, dict) else None
        if not candidate_id:
            return
        with get_conn() as conn:
            conn.execute(
                """UPDATE shadow_candidates
                   SET final_outcome = ?, gate_reason = ?, gate_detail = ?,
                       linked_trade_id = ?, resolved_at = ?
                   WHERE candidate_id = ? AND final_outcome = 'pending'""",
                (outcome, reason_code, reason_detail, trade_id, _now_et().isoformat(), candidate_id),
            )
    except Exception:
        logger.warning("shadow candidate resolve failed (non-fatal)", exc_info=True)
