"""Pure audit replay. No broker, settings, or execution imports."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


def clock(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Timezone missing")
    return value


def replay(trade, activation=65, giveback=35, time_barrier=None):
    entry = clock(trade["entry_time"])
    deadline = clock(trade["deadline"])
    if deadline <= entry:
        raise ValueError("Invalid deadline")
    if time_barrier:
        deadline = min(deadline, entry + timedelta(minutes=time_barrier))
    cost = Decimal(str(trade["entry_price"]))
    quantity = int(trade["quantity"])
    fees = Decimal(str(trade["fees"]))
    if cost <= 0 or quantity <= 0:
        raise ValueError("Invalid position")
    peak, armed, decision, minute = None, False, None, None
    previous = entry
    for quote in sorted(trade["option_path"], key=lambda q: clock(q["time"])):
        now = clock(quote["time"])
        bid, ask = Decimal(str(quote["bid"])), Decimal(str(quote["ask"]))
        if now <= entry or not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            continue
        if (now - previous).total_seconds() > 121:
            return {"status": "price_gap", "at": now.isoformat()}
        previous = now
        if decision is None and now >= deadline:
            decision = deadline
        if decision is not None:
            delay = (now - decision).total_seconds()
            if delay < 1:
                continue
            if delay > 121:
                return {"status": "missing_fill"}
            return {"status": "priced", "net": float((bid-cost)*100*quantity-fees),
                    "decision": decision.isoformat(), "fill_time": now.isoformat(),
                    "fill_bid": float(bid)}
        current_minute = now.replace(second=0, microsecond=0)
        if current_minute == minute:
            continue
        minute = current_minute
        gain = (bid-cost)*100
        if not time_barrier:
            armed = armed or gain >= activation
            if armed:
                peak = max(peak if peak is not None else gain, gain)
                if gain < peak * (1-Decimal(giveback)/100):
                    decision = now
    return {"status": "capture_ends_before_exit"}


def enrich(trade):
    """Preserve unavailable values rather than imputing Greeks or candles."""
    trade["time_of_day_et"] = clock(trade["entry_time"]).astimezone(
        ZoneInfo("America/New_York")).strftime("%H:%M:%S")
    profits = [(float(q["bid"])-trade["entry_price"])*100*trade["quantity"]
               for q in trade["option_path"]
               if q.get("bid") is not None and q.get("ask") is not None
               and 0 < float(q["bid"]) <= float(q["ask"])
               and clock(trade["entry_time"]) <= clock(q["time"]) <= clock(trade["exit_time"])]
    trade["observed_mfe"] = max([0.0]+profits) if profits else None
    trade["observed_mae"] = min([0.0]+profits) if profits else None
    return trade
