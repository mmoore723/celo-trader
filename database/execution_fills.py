"""Apply broker-confirmed fills and recovery cursors in one SQLite transaction.

Only new execution records are handled here. Closed historical trades are not
rewritten. Partial exits create closed child rows and reduce the open remainder.
"""
import json
from datetime import datetime, timezone

from database.execution_recovery import connect, save
from database.helpers import _to_et_isoformat, _merge_annotations_json
from broker.recovery_totals import totals

ENTRY_FIELDS = {
    "ticker", "contract_symbol", "option_type", "strike", "expiry", "entry_reason",
    "paper", "strategy_id", "tier", "broker_account_id", "candidate_id", "annotations_json",
}


def _insert(conn, values):
    keys = list(values)
    return conn.execute(
        f"INSERT INTO trades ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
        [values[key] for key in keys],
    ).lastrowid


def _entry(conn, record, quantity, notional, timestamp, fill_time, order_id):
    context = record["context"]
    values = {k: v for k, v in context["entry_record"].items() if k in ENTRY_FIELDS}
    price = notional / quantity
    values.update(
        contracts=quantity, entry_price=price, entry_time=timestamp,
        entry_fill_time=fill_time, entry_order_id=order_id, status="open",
        stop_price=round(price * context["stop_factor"], 4),
        target_price=round(price * context["target_factor"], 4),
    )
    if record.get("trade_id"):
        row = conn.execute("SELECT * FROM trades WHERE id=?", (record["trade_id"],)).fetchone()
        if row is None or row["status"] != "open" or row["contracts"] != record.get("applied_qty", 0):
            raise ValueError("Late entry fill conflicts with journal state")
        conn.execute("""UPDATE trades SET contracts=?, entry_price=?, stop_price=?,
            target_price=?, entry_fill_time=COALESCE(?, entry_fill_time) WHERE id=?""", (
            quantity, price, values["stop_price"], values["target_price"], fill_time, record["trade_id"],
        ))
    else:
        record["trade_id"] = _insert(conn, values)
        journal_context = {"recovery_id": record["id"], "contract": {"symbol": record["symbol"]},
                           "strategy_meta": {"shadow_candidate_id": values.get("candidate_id")}}
        conn.execute("""INSERT INTO signal_journal
            (ts,ticker,strategy_id,direction,confidence,outcome,reason_code,reason_detail,
             trade_id,context_json,tier,broker_account_id) VALUES(?,?,?,?,?,'entered',?,?,?,?,?,?)""", (
            timestamp, values["ticker"], values["strategy_id"], context.get("direction"),
            context.get("confidence"), "broker_confirmed", "Entry recorded from confirmed broker execution",
            record["trade_id"], json.dumps(journal_context), values.get("tier", "main"), record["journal_account"],
        ))
    if values.get("candidate_id"):
        conn.execute("""UPDATE shadow_candidates SET linked_trade_id=?, final_outcome='entered',
            resolved_at=? WHERE candidate_id=?""", (record["trade_id"], timestamp, values["candidate_id"]))
    return record["trade_id"], 0.0


def _exit(conn, record, quantity, price, timestamp, fill_time, order_id):
    context = record["context"]
    row = conn.execute("SELECT * FROM trades WHERE id=?", (context["trade_id"],)).fetchone()
    if row is None or row["status"] != "open" or row["contracts"] < quantity:
        raise ValueError("Exit fill conflicts with journal quantity")
    if row["contract_symbol"] != record["symbol"] or row["broker_account_id"] != record["journal_account"]:
        raise ValueError("Exit fill/account mismatch")
    trade = dict(row)
    remaining = trade["contracts"] - quantity
    if remaining:
        fields = ENTRY_FIELDS | {"entry_price", "entry_time", "entry_order_id", "entry_fill_time"}
        child = {key: trade.get(key) for key in fields}
        child.update(contracts=quantity, status="open", parent_trade_id=trade.get("parent_trade_id") or trade["id"])
        trade_id = _insert(conn, child)
        conn.execute("UPDATE trades SET contracts=? WHERE id=?", (remaining, trade["id"]))
    else:
        trade_id = trade["id"]
    from config import COMMISSION_PER_CONTRACT
    fee = 0 if record["paper"] else quantity * COMMISSION_PER_CONTRACT * 2
    pnl = (price - trade["entry_price"]) * quantity * 100 - fee
    recap = (f"{trade['strategy_id']} | {trade['ticker']} | {quantity} contract(s). "
             f"Entry ${trade['entry_price']:.4f} → confirmed exit ${price:.4f}. "
             f"Reason: {context['exit_reason']}.")
    conn.execute("""UPDATE trades SET status='closed', exit_price=?, exit_time=?,
        exit_reason=?, realized_pnl=?, exit_order_id=?, exit_fill_time=?,
        peak_price=?, mae_price=?, recap=?, annotations_json=? WHERE id=?""", (
        price, timestamp, context["exit_reason"], pnl, order_id, fill_time,
        context.get("peak_price") or trade["entry_price"],
        context.get("mae_price") or trade["entry_price"], recap,
        _merge_annotations_json(trade.get("annotations_json"), context.get("exit_annotations")), trade_id,
    ))
    day = timestamp[:10]
    conn.execute("""INSERT OR REPLACE INTO daily_summary
        SELECT ?, COALESCE(SUM(realized_pnl),0), COUNT(*), COALESCE(SUM(realized_pnl>0),0)
        FROM trades WHERE status='closed' AND substr(exit_time,1,10)=?""", (day, day))
    return trade_id, pnl


def apply_fills(store, record):
    """Replaying the same snapshot is a no-op, including after a process restart."""
    quantity, notional, final, filled_at, order_ids = totals(record)
    fill_time = _to_et_isoformat(filled_at) if filled_at else None
    timestamp = fill_time or _to_et_isoformat(datetime.now(timezone.utc))
    with connect(store.path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        saved = conn.execute("SELECT body FROM execution_recovery WHERE id=? AND account=?",
                             (record["id"], store.account)).fetchone()
        if saved is None or record["account"] != store.account:
            raise ValueError("Recovery record/account mismatch")
        current = json.loads(saved[0])
        previous_qty = current.get("applied_qty", 0)
        previous_cost = current.get("applied_notional", 0.0)
        for key in ("trade_id", "applied_qty", "applied_notional"):
            if key in current:
                record[key] = current[key]
        delta = quantity - previous_qty
        if delta < 0 or (delta == 0 and abs(notional - previous_cost) > 0.00001):
            raise ValueError("Previously booked fills changed; broker correction audit required")
        result = None
        if delta:
            order_id = order_ids[-1]
            delta_price = (notional - previous_cost) / delta
            if delta_price <= 0:
                raise ValueError("Invalid incremental fill price")
            args = conn, record, quantity, notional, timestamp, fill_time, order_id
            if record["side"] == "buy":
                trade_id, pnl = _entry(*args)
            else:
                trade_id, pnl = _exit(conn, record, delta, delta_price, timestamp, fill_time, order_id)
            conn.executemany("UPDATE broker_order_events SET linked_trade_id=? WHERE order_id=?",
                             [(trade_id, oid) for oid in order_ids])
            result = {"id": order_id, "filled_qty": delta,
                      "confirmed_fill_price": delta_price, "filled_avg_price": delta_price,
                      "filled_at": filled_at, "partial_fill": quantity < record["qty"],
                      "status": "filled" if quantity == record["qty"] else "partially_filled",
                      "recovery_id": record["id"], "accounted_trade_id": trade_id,
                      "accounted_pnl": pnl, "recovery_pending": not final}
            record["last_result"] = result
            conn.execute("""INSERT INTO broker_order_events
                (event_time,attempt_id,broker,broker_account_id,paper,order_id,event_type,
                 status,contract_symbol,side,requested_qty,filled_qty,fill_price,linked_trade_id,message,is_issue)
                VALUES(?,?,'alpaca',?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                timestamp, record["id"], record["journal_account"], int(record["paper"]), order_id,
                "filled" if quantity == record["qty"] else "partial_filled", result["status"],
                record["symbol"], record["side"], record["qty"], quantity, notional / quantity,
                trade_id, "Confirmed fills committed atomically; " + ("order terminal" if final else "remainder unresolved"),
                int(not final),
            ))
            conn.execute("INSERT INTO system_events(ts,level,component,message) VALUES(?,?,?,?)",
                         (timestamp, "INFO", "order", f"Broker-confirmed {record['side']} fill: "
                          f"{delta} {record['symbol']} @ {delta_price:.4f}; journal #{trade_id}."))
        record.update(applied_qty=quantity, applied_notional=notional, active=not final)
        save(conn, record)
    return result
