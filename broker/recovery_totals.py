"""Validate broker snapshots and aggregate confirmed fills without guessed prices."""
import math
from broker.recovery_tracking import TERMINAL


def totals(record):
    if record.get("replacement_unverified"):
        raise ValueError("Replacement parent status needs verification")
    quantity, notional, final, latest, order_ids = 0, 0.0, True, None, []
    for request in record["requests"]:
        if request["rejected"]:
            continue
        oid, seen = request.get("order_id"), set()
        if not oid:
            final = False
            continue
        parent_filled, branch = False, []
        while oid:
            if oid in seen or len(seen) >= 10:
                raise ValueError("Invalid replacement chain")
            seen.add(oid)
            branch.append(oid)
            order_ids.append(oid)
            order = record["snapshots"].get(oid, {})
            if order.get("replaced_by"):
                parent_filled |= float(order.get("filled_qty") or 0) > 0
                oid = order["replaced_by"]
                continue
            if parent_filled:
                from broker.recovery_activities import activity_totals
                count, cost, covered, fill_time = activity_totals(record, branch)
                quantity += count
                notional += cost
                final &= covered and order.get("status") in TERMINAL
                latest = fill_time or latest
                break
            qty = float(order.get("filled_qty") or 0)
            price = float(order.get("filled_avg_price") or 0)
            if not math.isfinite(qty) or qty < 0 or not qty.is_integer():
                raise ValueError("Invalid option fill quantity")
            if qty and (not math.isfinite(price) or price <= 0):
                raise ValueError("Filled quantity has no confirmed execution price")
            if order.get("status") == "filled" and qty == 0:
                raise ValueError("Filled order has no confirmed quantity")
            quantity += int(qty)
            notional += qty * price
            final &= order.get("status") in TERMINAL
            latest = order.get("filled_at") or latest
            break
    if quantity > record["qty"]:
        raise ValueError("Broker fills exceed requested quantity")
    return quantity, notional, final and not record.get("replacing"), latest, order_ids
