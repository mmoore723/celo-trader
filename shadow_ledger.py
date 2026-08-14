"""Paper-only candidate ledger for measuring router gates honestly.

It records raw strategy signals before the router's quality gates and links
their later journal outcome.  It is deliberately observational: it never
requests contracts, sends orders, or participates in position management.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from uuid import uuid4

from database import get_conn, _now_et

logger = logging.getLogger("celo_trader.shadow_ledger")


_OUTCOME_MINUTES = 60


def snapshot_candidate_plan(context: dict | None) -> None:
    """Persist the learner-facing plan against its raw scanner candidate.

    A qualified scanner signal can be stopped by an early guard before the
    normal signal journal writes its final outcome.  Keep the plan snapshot on
    ``shadow_candidates`` too, so Scanner Opportunities still has the actual
    contract screen, entry idea, and exit plan that existed at that moment.
    This is audit-only data; no order, sizing, or position code ever reads it.
    """
    try:
        if not isinstance(context, dict):
            return
        meta = context.get("strategy_meta")
        candidate_id = meta.get("shadow_candidate_id") if isinstance(meta, dict) else None
        if not candidate_id:
            return
        plan = {
            key: context[key]
            for key in ("entry_plan", "contract_recipe", "contract_preview", "contract_selection", "contract", "planned_quantity", "exit_plan")
            if key in context
        }
        if not plan:
            return
        with get_conn() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM shadow_candidates WHERE candidate_id = ?", (candidate_id,),
            ).fetchone()
            if row is None:
                return
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            metadata["manual_plan"] = plan
            conn.execute(
                "UPDATE shadow_candidates SET metadata_json = ? WHERE candidate_id = ?",
                (json.dumps(metadata, default=str, sort_keys=True), candidate_id),
            )
    except Exception:
        logger.warning("shadow candidate plan snapshot failed (non-fatal)", exc_info=True)


def record_router_candidate(ticker: str, signal: object, underlying_price: float | None = None) -> None:
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
        observed = _now_et()
        observed_at = observed.isoformat()
        try:
            entry_price = float(underlying_price) if underlying_price is not None else None
            if entry_price is not None and entry_price <= 0:
                entry_price = None
        except (TypeError, ValueError):
            entry_price = None
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO shadow_candidates
                   (candidate_id, observed_at, ticker, strategy_id, direction,
                    confidence, trigger_bar, tier, broker_account_id, metadata_json,
                    underlying_entry_price, outcome_due_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id, observed_at, ticker.upper(), str(getattr(signal, "strategy_id", "UNKNOWN")),
                    str(getattr(signal, "direction", "unknown")), float(getattr(signal, "confidence", 0.0)),
                    str(getattr(signal, "trigger_bar", "")), str(getattr(signal, "tier", "main")),
                    get_settings().get("active_broker_account_id") or None,
                    json.dumps(meta, default=str, sort_keys=True),
                    entry_price,
                    (observed + timedelta(minutes=_OUTCOME_MINUTES)).isoformat() if entry_price else None,
                ),
            )
        meta["shadow_candidate_id"] = candidate_id
    except Exception:
        logger.warning("shadow candidate write failed (non-fatal)", exc_info=True)


def resolve_due_directional_outcomes(ticker: str, underlying_price: float | None) -> None:
    """Record a same-session 60-minute directional result for due candidates.

    This deliberately measures the underlying's direction, not synthetic option
    P&L. It lets us judge whether a gate filtered useful directional setups
    without pretending we know a fill for a contract that was never selected.
    """
    try:
        from config import get_settings
        now = _now_et()
        price = float(underlying_price) if underlying_price is not None else 0.0
        if price <= 0:
            return
        account_id = get_settings().get("active_broker_account_id") or None
        clauses = [
            "ticker = ?", "outcome_due_at IS NOT NULL", "outcome_due_at <= ?",
            "outcome_observed_at IS NULL", "substr(observed_at, 1, 10) = ?",
        ]
        params: list[object] = [ticker.upper(), now.isoformat(), now.date().isoformat()]
        if account_id:
            clauses.append("broker_account_id = ?")
            params.append(account_id)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT candidate_id, direction, underlying_entry_price FROM shadow_candidates WHERE " +
                " AND ".join(clauses), tuple(params),
            ).fetchall()
            for row in rows:
                entry = float(row["underlying_entry_price"] or 0)
                if entry <= 0:
                    continue
                raw_move = (price - entry) / entry * 100
                directional = raw_move if row["direction"] == "bullish" else -raw_move
                conn.execute(
                    """UPDATE shadow_candidates SET underlying_exit_price = ?,
                       directional_move_pct = ?, direction_correct = ?, outcome_observed_at = ?
                       WHERE candidate_id = ? AND outcome_observed_at IS NULL""",
                    (price, round(directional, 4), int(directional > 0), now.isoformat(), row["candidate_id"]),
                )
    except Exception:
        logger.warning("shadow directional outcome write failed (non-fatal)", exc_info=True)


def resolve_candidate_from_context(
    context: dict | None, outcome: str, reason_code: str | None,
    reason_detail: str | None, trade_id: int | None,
) -> None:
    """Attach the final router/entry decision to its previously recorded candidate."""
    try:
        snapshot_candidate_plan(context)
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


def mark_candidate_observed_only(signal: object) -> None:
    """Finalize a raw signal that was measured but never eligible to order.

    This is how disabled/unvalidated strategies enter the learning ledger.
    It has no contract, broker, sizing, or position-management capability.
    """
    meta = getattr(signal, "meta", None)
    resolve_candidate_from_context(
        {"strategy_meta": meta if isinstance(meta, dict) else {}},
        "observed_only", "not_approved_for_entry",
        "Paper-only observation; this strategy was never allowed to place an order.", None,
    )
