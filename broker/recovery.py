"""Recover uncertain Alpaca orders without issuing blind retries."""
import functools
import hashlib
import inspect
import logging
import uuid

from broker.account_identity import resolve_account_identity, fallback_account_identity
from broker.recovery_tracking import TrackingBroker, poll_pending
from database.execution_fills import apply_fills
from database.execution_recovery import RecoveryStore, connect

logger = logging.getLogger("celo_trader.broker")


def scope(broker):
    from auth.context import get_current_user_id
    from config import get_db_path, get_settings
    settings, path = get_settings(), get_db_path()
    paper = broker.base == "https://paper-api.alpaca.markets"
    if broker.base not in {"https://paper-api.alpaca.markets", "https://api.alpaca.markets"}:
        raise ValueError("Unsupported execution route")
    if paper != bool(settings.get("paper_trading", True)):
        raise ValueError("Broker/database mode mismatch")
    cache_key = (get_current_user_id(), str(path), broker.base)
    cached = getattr(broker, "_recovery_scope", None)
    if cached and cached[0] == cache_key and cached[1].journal_account == settings.get("active_broker_account_id"):
        return cached[1]
    account = broker._get(f"{broker.base}/v2/account")
    if not account.get("id"):
        raise ValueError("Cannot verify broker account for recovery")
    identity = resolve_account_identity(broker.api_key, paper, account)
    aliases = {identity, fallback_account_identity(broker.api_key, paper)}
    if settings.get("active_broker_account_id") not in aliases:
        raise ValueError("Broker account does not match active journal account")
    store = RecoveryStore(path, identity)
    store.journal_account, store.aliases = settings["active_broker_account_id"], aliases
    broker._recovery_scope = cache_key, store
    return store


def _validate(store, args):
    context = args.get("order_context") or {}
    if args["side"] == "buy":
        entry = context.get("entry_record") or {}
        required = {"ticker", "contract_symbol", "option_type", "strike", "expiry", "strategy_id"}
        if not required.issubset(entry) or entry["contract_symbol"] != args["symbol"]:
            raise ValueError("Missing durable entry plan")
        if entry.get("broker_account_id") not in store.aliases:
            raise ValueError("Entry plan/account mismatch")
        if bool(entry.get("paper")) != (store.path.name == "trades_paper.db"):
            raise ValueError("Entry plan/mode mismatch")
        if not (0 < context.get("stop_factor", 0) < 1 < context.get("target_factor", 0)):
            raise ValueError("Missing entry protection plan")
        if context.get("direction") not in {"bullish", "bearish"} or context.get("confidence") is None:
            raise ValueError("Missing durable signal evidence")
        journal_account = entry["broker_account_id"]
    elif args["side"] == "sell":
        with connect(store.path) as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (context.get("trade_id"),)).fetchone()
        if (row is None or row["status"] != "open" or row["contract_symbol"] != args["symbol"]
                or row["broker_account_id"] not in store.aliases
                or row["contracts"] != context.get("expected_contracts")
                or row["contracts"] < args["qty"] or not context.get("exit_reason")):
            raise ValueError("Exit plan is stale or does not match the open journal trade")
        journal_account = row["broker_account_id"]
    else:
        raise ValueError("Unsupported option order side")
    if not isinstance(args["qty"], int) or args["qty"] <= 0:
        raise ValueError("Invalid option order quantity")
    return journal_account


def _issue(broker, message):
    from broker.common import _debounced_log
    broker.last_rejection_reason = None  # Unknown must never trigger phantom auto-close.
    broker.last_order_outcome = "recovery_pending"
    logger.warning("order_recovery_pending: %s", message)
    _debounced_log("ERROR", "order", f"Order recovery pending: {message}. No duplicate order sent.")


def _recover(broker, store, record):
    try:
        poll_pending(broker, store, record)
    except Exception as exc:
        # Retain last confirmed fills even when today's status query fails.
        _issue(broker, f"{record['symbol']}: {type(exc).__name__}")
    result = apply_fills(store, record)
    if record["active"]:
        _issue(broker, f"{record['symbol']}: awaiting terminal broker status")
    return result


def reconcile_orders(broker):
    """Safe to run before startup adoption and on every loop, including after hours."""
    if not getattr(type(broker), "durable_order_recovery", False):
        return set()
    store = scope(broker)
    for record in store.pending():
        with store.lock(record["symbol"]) as acquired:
            if not acquired:
                continue
            for current in store.pending(record["symbol"]):
                try:
                    _recover(broker, store, current)
                except Exception as exc:
                    _issue(broker, f"{current['symbol']}: {exc}")
    return {record["symbol"] for record in store.pending()}


def recoverable(method):
    signature = inspect.signature(method)

    @functools.wraps(method)
    def execute(broker, *args, **kwargs):
        if not getattr(type(broker), "durable_order_recovery", False):
            return method(broker, *args, **kwargs)
        broker.last_rejection_reason = None
        broker.last_order_outcome = "not_sent"
        values = dict(signature.bind(broker, *args, **kwargs).arguments)
        values.pop("self")
        context = values.get("order_context") or {}
        try:
            store = scope(broker)
            with store.lock(values["symbol"]) as acquired:
                if not acquired:
                    _issue(broker, f"{values['symbol']}: another request is managing this contract")
                    return None
                pending = store.pending(values["symbol"])
                if pending:
                    for record in pending:
                        _recover(broker, store, record)
                    # Caller sized this order before reconciliation: require a fresh tick.
                    broker.last_order_outcome = "reconciled_retry_next_tick"
                    return None
                journal_account = _validate(store, values)
                intent = context.get("intent_id")
                rid = hashlib.sha256(f"{store.account}:{intent}".encode()).hexdigest()[:32] if intent else uuid.uuid4().hex
                with connect(store.path) as conn:
                    if conn.execute("SELECT 1 FROM execution_recovery WHERE id=?", (rid,)).fetchone():
                        broker.last_order_outcome = "intent_already_processed"
                        return None
                record = {"id": rid, "account": store.account, "symbol": values["symbol"],
                          "journal_account": journal_account,
                          "side": values["side"], "qty": values["qty"], "context": context,
                          "paper": "paper" in broker.base, "active": True,
                          "requests": [], "snapshots": {}, "applied_qty": 0, "applied_notional": 0.0}
                store.put(record)
                tracker = TrackingBroker(broker, store, record)
                values["order_context"] = {**context, "execution_attempt_id": rid}
                legacy_result = method(tracker, **values)
                if any(o.get("replaced_by") for o in record["snapshots"].values()):
                    record["replacement_unverified"] = True
                    store.put(record)
                    poll_pending(broker, store, record)
                result = apply_fills(store, record)
                broker.last_rejection_reason = tracker.last_rejection_reason if not record["active"] else None
                broker.last_order_outcome = "recovery_pending" if record["active"] else "filled" if result else "no_fill"
                if result and legacy_result:
                    for key in ("execution_attempt_id", "order_intent_id"):
                        if key in legacy_result:
                            result[key] = legacy_result[key]
                if record["active"]:
                    _issue(broker, f"{record['symbol']}: original order still unresolved")
                return result
        except Exception as exc:
            _issue(broker, str(exc))
            return None
    return execute
