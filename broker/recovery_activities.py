"""Resolve fill-during-replace races using Alpaca's individual execution records."""
import math


def fetch_execution_fills(broker, store, record):
    snapshots = record["snapshots"]
    if not any(o.get("replaced_by") and float(o.get("filled_qty") or 0) > 0
               for o in snapshots.values()):
        return
    fills = dict(record.get("execution_fills") or {})
    for oid in snapshots:
        params = {"order_id": oid, "page_size": 100, "direction": "asc"}
        seen_tokens = set()
        for _ in range(10):
            page = broker._get(f"{broker.base}/v2/account/activities/FILL", params=params)
            if not isinstance(page, list):
                raise ValueError("Execution activity snapshot unavailable")
            for activity in page:
                if (activity.get("order_id") != oid or activity.get("symbol") != record["symbol"]
                        or activity.get("side") != record["side"] or not activity.get("id")):
                    raise ValueError("Execution activity does not match the tracked order")
                qty, price = float(activity["qty"]), float(activity["price"])
                if not (math.isfinite(qty) and qty > 0 and qty.is_integer()
                        and math.isfinite(price) and price > 0):
                    raise ValueError("Invalid execution activity quantity/price")
                fills[activity["id"]] = {key: activity.get(key) for key in (
                    "id", "order_id", "qty", "price", "cum_qty", "transaction_time")}
            if len(page) < 100:
                break
            token = page[-1]["id"]
            if token in seen_tokens:
                raise ValueError("Execution activity pagination did not advance")
            seen_tokens.add(token)
            params["page_token"] = token
        else:
            raise ValueError("Execution activity pagination limit reached")
    record["execution_fills"] = fills
    store.put(record)


def activity_totals(record, order_ids):
    fills = [f for f in (record.get("execution_fills") or {}).values() if f["order_id"] in order_ids]
    qty = sum(int(float(f["qty"])) for f in fills)
    notional = sum(float(f["qty"]) * float(f["price"]) for f in fills)
    complete = all(
        max((float(f.get("cum_qty") or 0) for f in fills if f["order_id"] == oid), default=0)
        >= float(record["snapshots"].get(oid, {}).get("filled_qty") or 0)
        for oid in order_ids
    )
    latest = max((f.get("transaction_time") or "" for f in fills), default="") or None
    return qty, notional, complete, latest
