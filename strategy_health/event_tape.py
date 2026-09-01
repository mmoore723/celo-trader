"""Account-scoped, chronological evidence tape for one trading session."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _day(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def _fetch(conn, sql: str, params: tuple[Any, ...]) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _event(kind: str, event_id: str, timestamp: str, row: dict) -> dict:
    trade_id = row.get("id") if kind.startswith("trade_") else row.get("trade_id")
    return {
        "event_id": f"{kind}:{event_id}", "timestamp": timestamp,
        "kind": kind, "ticker": row.get("ticker"),
        "strategy_id": row.get("strategy_id"),
        "candidate_id": row.get("candidate_id"),
        "trade_id": trade_id,
        "attempt_id": row.get("attempt_id"), "payload": row,
    }


def build_event_tape(conn, trading_date: str, mode: str, account_id: str | None) -> dict:
    """Assemble existing ledgers without writing or changing trading behavior."""
    day = _day(trading_date)
    if mode not in {"paper", "live"}:
        raise ValueError("mode must be paper or live")
    if not account_id:
        return {"date": day, "mode": mode, "account_scoped": False, "events": []}
    paper = 1 if mode == "paper" else 0
    events: list[dict] = []

    trades = _fetch(conn, """
        SELECT id, ticker, strategy_id, candidate_id, contract_symbol,
               entry_time, exit_time, entry_price, exit_price, realized_pnl,
               status, contracts, entry_order_id, exit_order_id
        FROM trades WHERE paper = ? AND broker_account_id = ?
          AND (substr(entry_time, 1, 10) = ? OR substr(exit_time, 1, 10) = ?)
    """, (paper, account_id, day, day))
    for row in trades:
        row["trade_id"] = row["id"]
        if str(row.get("entry_time") or "")[:10] == day:
            events.append(_event("trade_entry", str(row["id"]), row["entry_time"], row))
        if str(row.get("exit_time") or "")[:10] == day:
            events.append(_event("trade_exit", str(row["id"]), row["exit_time"], row))

    candidates = _fetch(conn, """
        SELECT candidate_id, observed_at, ticker, strategy_id, direction, trigger_bar,
               confidence, final_outcome, gate_reason, gate_detail,
               linked_trade_id, directional_move_pct, direction_correct,
               outcome_observed_at
        FROM shadow_candidates WHERE broker_account_id = ?
          AND substr(observed_at, 1, 10) = ?
    """, (account_id, day))
    for row in candidates:
        events.append(_event("candidate", row["candidate_id"], row["observed_at"], row))

    signals = _fetch(conn, """
        SELECT id, ts, ticker, strategy_id, direction, confidence, outcome,
               reason_code, reason_detail, trade_id, context_json
        FROM signal_journal WHERE broker_account_id = ? AND substr(ts, 1, 10) = ?
    """, (account_id, day))
    for row in signals:
        events.append(_event("signal", str(row["id"]), row["ts"], row))

    orders = _fetch(conn, """
        SELECT id, event_time, attempt_id, order_id, event_type, status,
               contract_symbol, ticker, strategy_id, candidate_id, intent_id,
               side, position_intent,
               requested_qty, filled_qty, order_type, limit_price, fill_price,
               latency_ms, message, is_issue, linked_trade_id AS trade_id
        FROM broker_order_events WHERE paper = ? AND broker_account_id = ?
          AND substr(event_time, 1, 10) = ?
    """, (paper, account_id, day))
    for row in orders:
        events.append(_event("order", str(row["id"]), row["event_time"], row))

    candidate_quotes = _fetch(conn, """
        SELECT q.id, q.candidate_id, q.observed_at, q.observation_kind,
               q.contract_symbol, q.bid, q.ask, q.mid, q.last, q.source,
               c.ticker, c.strategy_id
        FROM candidate_option_quote_observations q
        JOIN shadow_candidates c ON c.candidate_id = q.candidate_id
        WHERE c.broker_account_id = ? AND substr(c.observed_at, 1, 10) = ?
    """, (account_id, day))
    for row in candidate_quotes:
        events.append(_event("candidate_quote", str(row["id"]), row["observed_at"], row))

    alternative_quotes = _fetch(conn, """
        SELECT q.id, q.candidate_id, q.observed_at, q.observation_kind,
               q.contract_symbol, q.bid, q.ask, q.mid, q.policy_json, q.source,
               c.ticker, c.strategy_id
        FROM candidate_contract_alternatives q
        JOIN shadow_candidates c ON c.candidate_id = q.candidate_id
        WHERE c.broker_account_id = ? AND substr(c.observed_at, 1, 10) = ?
    """, (account_id, day))
    for row in alternative_quotes:
        events.append(_event(
            "candidate_contract_quote", str(row["id"]), row["observed_at"], row,
        ))

    trade_quotes = _fetch(conn, """
        SELECT q.id, q.trade_id, q.observed_at, q.observation_kind,
               q.contract_symbol, q.bid, q.ask, q.mid, q.last, q.fill_price,
               q.source, t.ticker, t.strategy_id
        FROM option_quote_observations q JOIN trades t ON t.id = q.trade_id
        WHERE t.paper = ? AND t.broker_account_id = ?
          AND substr(q.observed_at, 1, 10) = ?
    """, (paper, account_id, day))
    for row in trade_quotes:
        events.append(_event("trade_quote", str(row["id"]), row["observed_at"], row))

    candles = _fetch(conn, """
        SELECT id, ticker, timeframe, bar_time, open, high, low, close,
               volume, source, recorded_at
        FROM scanner_candle_observations WHERE broker_account_id = ?
          AND substr(bar_time, 1, 10) = ?
    """, (account_id, day))
    for row in candles:
        events.append(_event("market_bar", str(row["id"]), row["bar_time"], row))

    quotes = _fetch(conn, """
        SELECT id, ticker, observed_at, bid, ask, mid, source
        FROM underlying_quote_observations WHERE broker_account_id = ?
          AND substr(observed_at, 1, 10) = ?
    """, (account_id, day))
    for row in quotes:
        events.append(_event("underlying_quote", str(row["id"]), row["observed_at"], row))

    events.sort(key=lambda item: (item["timestamp"], item["event_id"]))
    return {"date": day, "mode": mode, "account_scoped": True, "events": events}
