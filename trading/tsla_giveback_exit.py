from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from trading.decision_trace import decision, note


STATE_KEY = "tsla_giveback_65_35_v1"
EXIT_REASON = "tsla_giveback_65_35"


def use_giveback_market_order(trade, reason, paper):
    return bool(trade.get("paper") in (True, False, 0, 1) and bool(trade["paper"]) == bool(paper)
                and str(trade.get("ticker") or "").upper() == "TSLA"
                and str(trade.get("strategy_id") or "").upper() == "V2_TSLA_TWO_LEG_TREND_PULLBACK"
                and reason == EXIT_REASON)


@decision
def giveback_exit(state, entry_price, bid, now):
    if now.tzinfo is None:
        raise ValueError("Aware clock required")
    if state.get("pending"):
        return True, EXIT_REASON
    minute = now.replace(second=0, microsecond=0).isoformat()
    previous = state.get("minute")
    if previous and datetime.fromisoformat(minute) <= datetime.fromisoformat(previous):
        return False, "hold"
    try:
        entry, value = Decimal(str(entry_price)), Decimal(str(bid))
    except (InvalidOperation, TypeError, ValueError):
        return False, "hold"
    if not entry.is_finite() or not value.is_finite() or entry <= 0 or value <= 0:
        return False, "hold"
    gain = (value - entry) * 100
    state["minute"] = minute
    if gain >= Decimal("65"):
        state["armed"] = True
    if not state.get("armed"):
        return False, "hold"
    peak = max(Decimal(state.get("peak", str(gain))), gain)
    state["peak"] = str(peak)
    if gain < peak * Decimal("0.65"):
        state["pending"] = True
        return True, EXIT_REASON
    return False, "hold"


@decision
def evaluate_tsla_giveback(trade, entry_time, now, quote):
    if (str(trade.get("strategy_id") or "").upper() != "V2_TSLA_TWO_LEG_TREND_PULLBACK"
            or str(trade.get("ticker") or "").upper() != "TSLA"
            or trade.get("paper") not in (True, False, 0, 1)):
        return None
    if entry_time is None or now <= entry_time:
        return False, "hold"
    from database import get_conn
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT strategy_context_json FROM trades WHERE id=? AND status='open' AND paper=? AND broker_account_id IS ?",
            (trade["id"], int(bool(trade["paper"])), trade.get("broker_account_id")),
        ).fetchone()
        if row is None:
            return False, "hold"
        context = json.loads(row[0]) if row[0] else {}
        state = dict(context.get(STATE_KEY) or {})
        note('giveback_persisted_state_read',state)
        if state.get("pending"):
            return True, EXIT_REASON
        if not quote or quote.get("symbol") != trade["contract_symbol"]:
            note('giveback_quote_rejected',{'reason':'missing_or_wrong_contract'})
            return False, "hold"
        try:
            received = datetime.fromisoformat(quote["quote_received_at"])
            bid, ask = Decimal(str(quote["bid"])), Decimal(str(quote["ask"]))
            age = quote.get("quote_age_seconds")
            if (received.tzinfo is None or not timedelta(0) <= now - received <= timedelta(seconds=60)
                    or not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask
                    or age is None or not 0 <= float(age) <= 60):
                note('giveback_quote_rejected',{'reason':'quote_freshness_or_price_validation'})
                return False, "hold"
        except (KeyError, TypeError, ValueError, InvalidOperation):
            note('giveback_quote_rejected',{'reason':'quote_fields_invalid'})
            return False, "hold"
        result = giveback_exit(state, trade["entry_price"], bid, now)
        if state != context.get(STATE_KEY):
            context[STATE_KEY] = state
            conn.execute("UPDATE trades SET strategy_context_json=? WHERE id=? AND paper=? AND broker_account_id IS ?",
                         (json.dumps(context), trade["id"], int(bool(trade["paper"])), trade.get("broker_account_id")))
        return result
