"""Durable request IDs and raw broker responses; never persist credentials."""
import math

TERMINAL = {"filled", "canceled", "cancelled", "expired", "rejected"}
FIELDS = {"id", "client_order_id", "status", "filled_qty", "filled_avg_price",
          "filled_at", "updated_at", "replaced_by", "replaces", "symbol", "side", "qty"}


def snapshot(record, order, order_id=None):
    oid = str(order.get("id") or order_id or "")
    if not oid:
        raise ValueError("Broker response has no order ID")
    if order_id and oid != str(order_id):
        raise ValueError("Broker returned a different order ID")
    if order.get("symbol") and order["symbol"] != record["symbol"]:
        raise ValueError("Broker order symbol mismatch")
    if order.get("side") and order["side"] != record["side"]:
        raise ValueError("Broker order side mismatch")
    previous = record["snapshots"].get(oid, {})
    qty = float(order.get("filled_qty") or 0)
    if not math.isfinite(qty) or qty < 0 or not qty.is_integer():
        raise ValueError("Invalid option fill quantity")
    if qty < float(previous.get("filled_qty") or 0):
        raise ValueError("Broker fill quantity moved backwards")
    clean = {key: order[key] for key in FIELDS if key in order}
    record["snapshots"][oid] = {**previous, **clean, "id": oid}
    return oid


class TrackingBroker:
    def __init__(self, broker, store, record):
        self.broker, self.store, self.record = broker, store, record
        self.last_rejection_reason = None

    def __getattr__(self, name):
        return getattr(self.broker, name)

    def _wait_for_fill(self, *args, **kwargs):
        from broker.alpaca_orders import AlpacaOrdersMixin
        return AlpacaOrdersMixin._wait_for_fill(self, *args, **kwargs)

    def _post(self, url, payload):
        if not url.endswith("/v2/orders"):
            raise ValueError("Unexpected order endpoint")
        index = len(self.record["requests"])
        cid = payload.get("client_order_id") or f"celo-{self.record['id'][:28]}-{index}"
        request = {"client_id": cid, "order_id": None, "rejected": False}
        self.record["requests"].append(request)
        self.store.put(self.record)  # Commit BEFORE the network side effect.
        try:
            result = self.broker._post(url, {**payload, "client_order_id": cid})
        except Exception as exc:
            response = getattr(exc, "response", None)
            duplicate = response is not None and "client_order_id" in response.text
            if getattr(response, "status_code", None) in {400, 401, 403, 422} and not duplicate:
                request["rejected"] = True
            self.store.put(self.record)
            raise
        request["order_id"] = snapshot(self.record, result)
        if result.get("client_order_id") and result["client_order_id"] != cid:
            raise ValueError("Broker response has a different client order ID")
        self.store.put(self.record)
        return result

    def _get(self, url, params=None):
        result = self.broker._get(url, params=params) if params else self.broker._get(url)
        if "/v2/orders/" in url:
            snapshot(self.record, result, url.rsplit("/", 1)[-1])
            self.store.put(self.record)
        return result

    def _patch(self, url, payload):
        oid = url.rsplit("/", 1)[-1]
        current = self.record["snapshots"].get(oid, {})
        if float(current.get("filled_qty") or 0) > 0:
            raise ValueError("Keep partial fill at existing limit; reconcile before replacement")
        self.record["replacing"] = oid
        self.store.put(self.record)
        result = self.broker._patch(url, payload)
        child = snapshot(self.record, result)
        if child != oid:
            self.record["snapshots"].setdefault(oid, {"id": oid}).update(
                status="replaced", replaced_by=child)
        self.record["replacing"] = None
        self.store.put(self.record)
        return result

    def get_open_orders(self, symbol=None):
        # Legacy submission-error cleanup must not cancel unrelated orders.
        return []


def poll_pending(broker, store, record):
    """Recover lost IDs, follow replacements, request cancellation of working remainder."""
    for request in record["requests"]:
        if request["rejected"]:
            continue
        oid = request.get("order_id")
        if not oid:
            order = broker._get(f"{broker.base}/v2/orders:by_client_order_id",
                                params={"client_order_id": request["client_id"]})
            if order.get("client_order_id") != request["client_id"]:
                raise ValueError("Recovered order client ID mismatch")
            oid = request["order_id"] = snapshot(record, order)
            store.put(record)
        visited = set()
        while oid and oid not in visited and len(visited) < 10:
            visited.add(oid)
            order = broker._get(f"{broker.base}/v2/orders/{oid}")
            snapshot(record, order, oid)
            store.put(record)
            if order.get("replaced_by"):
                oid = order["replaced_by"]
                continue
            if order.get("status") not in TERMINAL:
                broker.cancel_order(oid)  # Acceptance is not proof of cancellation.
            break
        else:
            raise ValueError("Invalid replacement chain")
    record["replacing"] = None
    record["replacement_unverified"] = False
    from broker.recovery_activities import fetch_execution_fills
    fetch_execution_fills(broker, store, record)
    store.put(record)
