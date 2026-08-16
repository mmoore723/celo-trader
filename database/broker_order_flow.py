"""Durable Alpaca order-lifecycle ledger and health summary.

The trading tables describe positions after a confirmed fill.  This ledger
describes the transport path before and after that point so a rejected,
timed-out, partially-filled, or unlinked order cannot disappear between log
lines.  Writes are best-effort at the broker boundary; callers must never let
an observability failure prevent an order from being managed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from database.connection import _conn_for_mode, get_conn
from database.helpers import _to_et_isoformat

_ET = ZoneInfo("America/New_York")
_TERMINAL_EVENTS = {
    "filled", "partial_filled", "terminal_no_fill", "submission_error",
    "fill_unconfirmed", "fallback_unconfirmed", "live_timeout",
    "not_sent_missing_credentials", "orphan_cancelled", "orphan_sweep_failed",
}


def record_broker_order_event(
    *,
    attempt_id: str,
    event_type: str,
    order_id: str | None = None,
    parent_order_id: str | None = None,
    status: str | None = None,
    contract_symbol: str | None = None,
    ticker: str | None = None,
    strategy_id: str | None = None,
    side: str | None = None,
    position_intent: str | None = None,
    requested_qty: int | None = None,
    filled_qty: int | None = None,
    order_type: str | None = None,
    limit_price: float | None = None,
    fill_price: float | None = None,
    latency_ms: float | None = None,
    message: str | None = None,
    is_issue: bool = False,
    linked_trade_id: int | None = None,
    broker_account_id: str | None = None,
    paper: bool | None = None,
) -> int:
    """Append one sanitized order event and return its row id."""
    from config import get_settings

    settings = get_settings()
    if paper is None:
        paper = bool(settings.get("paper_trading", True))
    if broker_account_id is None:
        broker_account_id = settings.get("active_broker_account_id") or None
    event_time = _to_et_isoformat(datetime.now(_ET))
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO broker_order_events (
                event_time, attempt_id, broker, broker_account_id, paper,
                order_id, parent_order_id, event_type, status,
                contract_symbol, ticker, strategy_id, side, position_intent,
                requested_qty, filled_qty, order_type, limit_price, fill_price,
                latency_ms, message, is_issue, linked_trade_id
            ) VALUES (?, ?, 'alpaca', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_time, attempt_id, broker_account_id, int(bool(paper)),
                order_id, parent_order_id, event_type, status,
                contract_symbol, ticker, strategy_id, side, position_intent,
                requested_qty, filled_qty, order_type, limit_price, fill_price,
                latency_ms, message, int(bool(is_issue)), linked_trade_id,
            ),
        )
        return int(cur.lastrowid)


def link_broker_order_to_trade(
    order_id: str | None,
    trade_id: int,
    *,
    link_kind: str,
) -> None:
    """Link every event for an Alpaca order to the DB trade it produced."""
    if not order_id:
        return
    with get_conn() as conn:
        row = conn.execute(
            """SELECT attempt_id, contract_symbol, ticker, strategy_id, side,
                      position_intent, requested_qty
               FROM broker_order_events WHERE order_id = ?
               ORDER BY id DESC LIMIT 1""",
            (order_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE broker_order_events SET linked_trade_id = ? WHERE attempt_id = ?",
            (trade_id, row["attempt_id"]),
        )
        conn.execute(
            """
            INSERT INTO broker_order_events (
                event_time, attempt_id, broker, broker_account_id, paper,
                order_id, event_type, status, contract_symbol, ticker,
                strategy_id, side, position_intent, requested_qty,
                message, is_issue, linked_trade_id
            )
            SELECT ?, attempt_id, broker, broker_account_id, paper,
                   ?, 'linked_to_trade', 'linked', contract_symbol, ticker,
                   strategy_id, side, position_intent, requested_qty,
                   ?, 0, ?
            FROM broker_order_events WHERE attempt_id = ? ORDER BY id DESC LIMIT 1
            """,
            (
                _to_et_isoformat(datetime.now(_ET)), order_id,
                f"{link_kind} order linked to trade #{trade_id}", trade_id,
                row["attempt_id"],
            ),
        )


def get_broker_order_flow(
    *,
    mode: str = "paper",
    trading_date: str | None = None,
    broker_account_id: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return grouped attempts, events, summary counts, and active issues."""
    if mode not in {"paper", "live"}:
        raise ValueError("mode must be paper or live")
    if trading_date is None:
        trading_date = datetime.now(_ET).date().isoformat()
    try:
        datetime.strptime(trading_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc

    clauses = ["substr(event_time, 1, 10) = ?", "paper = ?"]
    params: list[Any] = [trading_date, 1 if mode == "paper" else 0]
    if broker_account_id:
        clauses.append("broker_account_id = ?")
        params.append(broker_account_id)
    params.append(max(1, min(int(limit), 2000)))
    with _conn_for_mode(mode) as conn:
        rows = conn.execute(
            f"""SELECT * FROM broker_order_events
                 WHERE {' AND '.join(clauses)}
                 ORDER BY id DESC LIMIT ?""",
            params,
        ).fetchall()

    events = [dict(row) for row in rows]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in reversed(events):
        grouped[str(event["attempt_id"])].append(event)

    now = datetime.now(_ET)
    attempts: list[dict[str, Any]] = []
    for attempt_id, stages in grouped.items():
        first, last = stages[0], stages[-1]
        filled = next((e for e in reversed(stages) if e["event_type"] in {"filled", "partial_filled"}), None)
        linked = next((e for e in reversed(stages) if e["linked_trade_id"] is not None), None)
        issue_events = [e for e in stages if bool(e["is_issue"])]
        last_type = str(last["event_type"])
        terminal = last_type in _TERMINAL_EVENTS or filled is not None
        try:
            age_seconds = max(0, int((now - datetime.fromisoformat(str(last["event_time"]))).total_seconds()))
        except Exception:
            age_seconds = 0
        stale = not terminal and age_seconds > 60
        unlinked_fill = bool(filled and not linked and age_seconds > 120)
        active_issue = stale or unlinked_fill or (
            bool(last["is_issue"])
            and last_type not in {"status_poll_error", "price_step_failed", "orphan_cancelled"}
        )
        attempts.append({
            "attempt_id": attempt_id,
            "started_at": first["event_time"],
            "updated_at": last["event_time"],
            "order_id": last["order_id"] or next((e["order_id"] for e in reversed(stages) if e["order_id"]), None),
            "contract_symbol": last["contract_symbol"] or first["contract_symbol"],
            "ticker": last["ticker"] or first["ticker"],
            "strategy_id": last["strategy_id"] or first["strategy_id"],
            "side": last["side"] or first["side"],
            "position_intent": last["position_intent"] or first["position_intent"],
            "requested_qty": first["requested_qty"],
            "filled_qty": filled["filled_qty"] if filled else None,
            "fill_price": filled["fill_price"] if filled else None,
            "final_event": last_type,
            "final_status": last["status"],
            "linked_trade_id": linked["linked_trade_id"] if linked else None,
            "had_issue": bool(issue_events),
            "active_issue": active_issue,
            "issue_message": (
                "Alpaca fill has not been linked to a bot trade" if unlinked_fill else
                "Order lifecycle has not advanced for more than 60 seconds" if stale else
                (issue_events[-1]["message"] if issue_events else None)
            ),
            "events": stages,
        })
    attempts.sort(key=lambda item: item["updated_at"], reverse=True)

    return {
        "date": trading_date,
        "mode": mode,
        "account_scoped": bool(broker_account_id),
        "summary": {
            "attempts": len(attempts),
            "acknowledged": sum(any(e["event_type"] in {"acknowledged", "fallback_acknowledged"} for e in a["events"]) for a in attempts),
            "filled": sum(a["filled_qty"] is not None for a in attempts),
            "rejected_or_failed": sum(a["final_event"] in {"submission_error", "terminal_no_fill", "fill_unconfirmed", "fallback_unconfirmed", "live_timeout", "not_sent_missing_credentials"} for a in attempts),
            "active_issues": sum(bool(a["active_issue"]) for a in attempts),
            "unlinked_fills": sum(a["filled_qty"] is not None and a["linked_trade_id"] is None for a in attempts),
        },
        "attempts": attempts,
    }
