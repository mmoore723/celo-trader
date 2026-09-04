"""Rebuild execution-related state from durable journal evidence, not guessed fills."""
from database import get_conn


def restore_stage1(trade, position_state):
    if position_state.get("stage1_done"):
        return
    with get_conn() as conn:
        closed = conn.execute("""SELECT 1 FROM trades WHERE parent_trade_id=?
            AND broker_account_id=? AND status='closed' AND exit_reason LIKE 'stage1%'
            LIMIT 1""", (trade.get("parent_trade_id") or trade["id"], trade.get("broker_account_id"))).fetchone()
    if closed:
        from config import STAGE2_TRAIL_PCT
        position_state["stage1_done"] = True
        position_state["stage1_be_price"] = round(trade["entry_price"] * (1 + STAGE2_TRAIL_PCT), 4)
        if str(position_state.get("exit_pending_reason") or "").startswith("stage1"):
            position_state.pop("exit_pending_reason", None)
            position_state.pop("exit_pending_since", None)
            position_state["exit_attempts"] = 0


def restore_entries(state, account, day):
    with get_conn() as conn:
        rows = conn.execute("""SELECT DISTINCT ticker FROM trades
            WHERE substr(entry_time,1,10)=? AND broker_account_id=? AND entry_order_id IS NOT NULL""",
                            (day, account)).fetchall()
    state.setdefault("orb_entered_today", set()).update(row[0] for row in rows)
