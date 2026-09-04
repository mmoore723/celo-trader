"""
broker/alpaca_orders.py — AlpacaOrdersMixin: options order submission and
fill confirmation.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Alpaca*Mixin classes
into AlpacaClient in broker/alpaca_client.py.

_wait_for_fill is kept as ONE function rather than split further: it is a
single ordered polling loop (poll status -> handle partial fill -> step
price -> re-poll -> timeout handling) built on tightly-coupled local mutable
state read by many later steps in the loop — the same "irreducible
sequential function" exception applied to trading/entry/tick.py's _tick and
trading/position_manager/close.py's _close_position. This is live-money
order-execution code; splitting its body would require redesigning its
internal state-passing contract, risking a subtle live-trading bug for a
cosmetic line-count win. place_option_order is kept alongside it because it
calls self._wait_for_fill directly and the two form one order lifecycle.
"""

import logging
import math
import time
import uuid
from time import monotonic
from typing import Optional

from database import log_event, record_broker_order_event
from broker.common import _extract_partial_fill
from broker.recovery import recoverable
from broker.option_quote_quality import opra_quote_problem

logger = logging.getLogger("celo_trader.broker")


def _record_flow(**event) -> None:
    """Best-effort observability: monitoring must never break order management."""
    try:
        record_broker_order_event(**event)
    except Exception:
        logger.warning("broker_order_event_write_failed", exc_info=True)


class AlpacaOrdersMixin:

    # ── Options orders (FIX C1: correct Alpaca v2 options format) ────────────

    @recoverable
    def place_option_order(
        self,
        symbol: str,            # OCC option symbol e.g. AMC240119C00005000
        qty: int,
        side: str,              # 'buy' or 'sell'
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        step_to_price: Optional[float] = None,  # buy: step UP to ask; sell: step DOWN to bid
        max_acceptable_price: Optional[float] = None,  # entry ceiling; never chase above it
        allow_market_fallback: bool = False,  # emergency exits only
        position_intent: Optional[str] = None,  # 'buy_to_open' | 'sell_to_close' (FIX 2026-07-16)
        order_context: Optional[dict] = None,
        max_wait_seconds: Optional[int] = None,
        price_authority: str = "alpaca",
    ) -> Optional[dict]:
        """
        Submit an options order via Alpaca v2 OPTIONS endpoint.

        FIX C2: Single-leg option orders use the SAME FLAT shape as equity
        orders — symbol/qty/side/type/time_in_force at the top level.
        The previous "order_class: simple" + "legs": [...] shape is only
        valid for order_class "mleg" (multi-leg spreads); sending it for a
        single-leg order is rejected by Alpaca with 422 Unprocessable Entity
        (this was the cause of the JPM order failure on 2026-06-11).

        FIX 2026-07-16: Every caller here was sending only side="sell" with
        no position_intent, so Alpaca could not always match the order to an
        existing long position and priced it as a NEW naked/cash-secured
        short instead of a close — this is why an XLE exit was rejected
        needing $54,810 in buying power on a $728 account. Explicit
        position_intent ("buy_to_open" on entries, "sell_to_close" on exits)
        removes the ambiguity. Passing it is optional (None = old behavior)
        so any caller not yet updated keeps working exactly as before.

        Alpaca options docs (valid single-leg payload examples):
        https://docs.alpaca.markets/docs/options-orders
        """
        context = order_context or {}
        attempt_id = context.get("execution_attempt_id") or uuid.uuid4().hex
        intent_id = str(context.get("intent_id") or "").strip()
        flow_base = {
            "attempt_id": attempt_id,
            "contract_symbol": symbol,
            "ticker": context.get("ticker"),
            "strategy_id": context.get("strategy_id"),
            "candidate_id": context.get("candidate_id"),
            "intent_id": intent_id or None,
            "side": side,
            "position_intent": position_intent,
            "requested_qty": qty,
            "order_type": order_type,
            "limit_price": limit_price,
            "linked_trade_id": context.get("trade_id"),
        }
        if not getattr(self, "api_key", ""):
            logger.warning("Alpaca keys missing — order not sent")
            _record_flow(
                **flow_base, event_type="not_sent_missing_credentials",
                status="not_sent", message="Alpaca credentials are missing",
                is_issue=True,
            )
            return None

        # Reset from any previous call so a stale reason can never be misread
        # by this call's caller if this attempt doesn't hit the except block.
        self.last_rejection_reason = None

        normalized_price_authority = str(price_authority or "alpaca").strip().lower()
        if normalized_price_authority == "tradier":
            # Preserve the explicitly selected price authority for both sides.
            # Executing at Alpaca does not make its free indicative quotes NBBO.
            reference_bid = float(context.get("quote_bid") or 0)
            reference_ask = float(context.get("quote_ask") or 0)
            reference_mid = float(context.get("quote_mid") or 0)
            reference_latency_ms = context.get("quote_latency_ms")
            _record_flow(
                **{**flow_base, "limit_price": (reference_ask if side.lower() == "buy" else reference_bid) or limit_price},
                event_type="authoritative_quote", status="quoted",
                latency_ms=reference_latency_ms,
                message=(
                    f"Tradier authoritative {side.lower()} quote bid={reference_bid:.2f} "
                    f"ask={reference_ask:.2f} mid={reference_mid:.2f}; "
                    f"working limit={float(limit_price or 0):.2f}"
                ),
            )
            # Keep the existing bounded paper-entry step. Its ceiling comes
            # from the approved intent, not a modified indicative-feed quote.
            # No second quote request is needed to honor that price limit.
            is_paper_route = "paper" in str(self.base).lower()
            if is_paper_route and side.lower() == "buy" and position_intent == "buy_to_open":
                ceiling = float(max_acceptable_price or reference_ask or limit_price or 0)
                if math.isfinite(ceiling) and ceiling > float(limit_price or 0):
                    step_to_price = ceiling
                    _record_flow(
                        **{**flow_base, "limit_price": ceiling},
                        event_type="bounded_broker_reprice", status="quoted",
                        message=(f"Tradier initial limit={float(limit_price or 0):.2f}; "
                                 f"may step to approved ceiling={ceiling:.2f}. "
                                 "Alpaca indicative quotes are not used."),
                    )
                else:
                    _record_flow(
                        **flow_base, event_type="broker_reprice_rejected", status="bounded",
                        message="Working limit is already at the approved ceiling; no expansion.",
                    )
        else:
            # Optional broker repricing requires explicit, fresh OPRA. When
            # unavailable, preserve the caller's prices and exit urgency.
            external_source = str(context.get("quote_source") or "").strip()
            external_bid = float(context.get("quote_bid") or 0)
            external_ask = float(context.get("quote_ask") or 0)
            external_mid = float(context.get("quote_mid") or 0)
            if external_source and (external_bid > 0 or external_ask > 0):
                natural_reference = external_ask if side.lower() == "buy" else external_bid
                _record_flow(
                    **{**flow_base, "limit_price": natural_reference or limit_price},
                    event_type="external_reference_quote", status="quoted",
                    message=(
                        f"{external_source} bid={external_bid:.2f} "
                        f"ask={external_ask:.2f} mid={external_mid:.2f}; "
                        "reference before optional verified OPRA requote"
                    ),
                )
            try:
                broker_quote = self.get_latest_option_quote(symbol)
            except Exception:
                broker_quote = None
            quote_problem = opra_quote_problem(broker_quote, symbol)
            if quote_problem:
                _record_flow(
                    **flow_base, event_type="broker_quote_not_used", status="reference_preserved",
                    message=f"Alpaca quote not used: {quote_problem}; supplied limits retained.",
                )
            else:
                broker_bid = float(broker_quote.get("bp") or 0)
                broker_ask = float(broker_quote.get("ap") or 0)
                if broker_bid > 0 and broker_ask >= broker_bid:
                    broker_mid = round((broker_bid + broker_ask) / 2, 2)
                    if side.lower() == "buy":
                        ceiling = float(max_acceptable_price or broker_ask)
                        limit_price = min(broker_mid, ceiling)
                        step_to_price = min(broker_ask, ceiling)
                    else:
                        limit_price = broker_mid
                        step_to_price = broker_bid
                    flow_base["limit_price"] = limit_price
                    _record_flow(
                        **flow_base, event_type="broker_requote", status="quoted",
                        message=(
                            f"Alpaca OPRA quote t={broker_quote['t']} bid={broker_bid:.2f} "
                            f"ask={broker_ask:.2f}; working limit={limit_price:.2f}"
                        ),
                    )

        payload: dict = {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          side,
            "time_in_force": "day",
        }
        # The deterministic entry pipeline creates one authoritative intent
        # for the contract/quantity/price ceiling shown in Scanner
        # Opportunities.  Carry its id all the way to Alpaca so a broker order
        # can be reconciled to that exact learner-facing decision.
        if intent_id:
            payload["client_order_id"] = f"celo-{intent_id[:32]}"
        if position_intent:
            payload["position_intent"] = position_intent

        # Options orders should always be limit to avoid bad fills
        if order_type == "limit" and limit_price:
            payload["type"]        = "limit"
            payload["limit_price"] = str(round(limit_price, 2))
        else:
            payload["type"] = "market"

        logger.info(
            "order_submitted",
            extra={
                "event": "order_submitted",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "order_type": order_type,
                "limit_price": limit_price,
            },
        )
        _record_flow(
            **flow_base, event_type="submit_attempt", status="sending",
            message=f"Sending {side} {qty} contract(s) to Alpaca",
        )
        submit_started = monotonic()
        try:
            order = self._post(f"{self.base}/v2/orders", payload)
            order_id = order.get("id", "")
            _record_flow(
                **flow_base, event_type="acknowledged", order_id=order_id,
                status=order.get("status") or "accepted",
                latency_ms=round((monotonic() - submit_started) * 1000, 1),
                message="Alpaca acknowledged the order",
            )
            # Use module "order" (not "broker.alpaca") so this shows in THINKING tab.
            log_event("INFO", "order",
                      f"📤 [{symbol}] Order sent — {side.upper()} {qty}× {symbol} "
                      f"@ ${float(limit_price or 0):.2f} {payload['type']} (ID: {order_id[:8]}…). Waiting for fill…")

            # FIX S1: Poll for fill confirmation — don't record trade on pending.
            # Pass limit_price so paper fallback can use it for confirmed_fill_price.
            confirmed = self._wait_for_fill(order_id, limit_price=limit_price,
                                            step_to_price=step_to_price, side=side,
                                            symbol=symbol, qty=qty,
                                            allow_market_fallback=allow_market_fallback,
                                            position_intent=position_intent,
                                            attempt_id=attempt_id,
                                            order_context=context,
                                            max_wait=max_wait_seconds or 0)
            if not confirmed:
                log_event("ERROR", "order",
                          f"🟡 [{symbol}] Fill wait ended. Checking broker-confirmed fills "
                          f"and any unresolved remainder before another order.")
                logger.error(
                    "order_fill_timeout",
                    extra={
                        "event": "order_fill_timeout",
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                    },
                )
                return None
            confirmed_fill_price = float(
                confirmed.get("confirmed_fill_price")
                or confirmed.get("filled_avg_price")
                or 0
            )
            confirmed_qty = int(float(confirmed.get("filled_qty") or qty or 0))
            _record_flow(
                **{
                    **flow_base,
                    "limit_price": (
                        float(context.get("quote_ask" if side.lower() == "buy" else "quote_bid") or limit_price or 0)
                        if normalized_price_authority == "tradier"
                        else limit_price
                    ),
                },
                event_type="execution_summary",
                status="partially_filled" if confirmed_qty < qty else "filled",
                filled_qty=confirmed_qty,
                fill_price=confirmed_fill_price,
                latency_ms=round((monotonic() - submit_started) * 1000, 1),
                message=(
                    f"{normalized_price_authority} reference to Alpaca fill; "
                    f"working limit={float(limit_price or 0):.2f}"
                ),
            )
            confirmed["execution_attempt_id"] = attempt_id
            if intent_id:
                confirmed["order_intent_id"] = intent_id
            return confirmed

        except Exception as e:
            # FIX: surface Alpaca's ACTUAL rejection reason in the human-readable
            # audit log, instead of just the Python exception type (e.g.
            # "HTTPError"). Previously a 403 "insufficient options buying power"
            # "cost_basis" — pull those out for a specific, actionable message.
            _reason = type(e).__name__
            _resp = getattr(e, "response", None)
            if _resp is not None:
                try:
                    _body = _resp.json()
                    _msg  = _body.get("message", "")
                    if _msg == "insufficient options buying power":
                        _avail = float(_body.get("options_buying_power", 0))
                        _need  = float(_body.get("cost_basis", 0))
                        _reason = (
                            f"insufficient options buying power — this order "
                            f"needs ${_need:,.2f} but only ${_avail:,.2f} is "
                            f"available. Check your Alpaca paper dashboard's "
                            f"Positions tab for an open position tying up funds."
                        )
                    elif _msg:
                        _reason = _msg
                except Exception:
                    pass
            # Stored (not raised) so existing callers keep working unchanged —
            # they still just check `if fill is None`. Callers that specifically
            # need to distinguish "Alpaca truly has no matching position" (not
            # a transient/retry-worthy rejection) can check this afterward via
            # is_phantom_position_rejection(alpaca.last_rejection_reason).
            _recovery = getattr(self, "record", None)
            _uncertain = isinstance(_recovery, dict) and any(
                not request.get("rejected") for request in _recovery.get("requests", [])
            )
            self.last_rejection_reason = None if _uncertain else _reason
            _record_flow(
                **flow_base, event_type="submission_unconfirmed" if _uncertain else "submission_error",
                status="unknown" if _uncertain else "rejected", message=str(_reason), is_issue=True,
                latency_ms=round((monotonic() - submit_started) * 1000, 1),
            )
            log_event("ERROR", "order",
                      f"🟡 [{symbol}] Order response uncertain — checking the saved order ID before any retry."
                      if _uncertain else f"🔴 [{symbol}] Order rejected — {_reason}. No position opened.")
            logger.error(
                "order_execution_failed",
                extra={
                    "event": "order_execution_failed",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(e),
                },
            )

            # FIX 2026-06-15 GHOST PREVENTION: the exception above means
            # self._post() raised BEFORE returning an order_id, so we have no
            try:
                _orphans = self.get_open_orders(symbol=symbol)
                for _o in _orphans:
                    _oid = _o.get("id", "")
                    if self.cancel_order(_oid):
                        _record_flow(
                            **flow_base, event_type="orphan_cancelled",
                            order_id=_oid, status="cancelled",
                            message="Resting Alpaca order found and cancelled after submission error",
                            is_issue=True,
                        )
                        log_event(
                            "WARNING", "order",
                            f"🟡 [{symbol}] Found and cancelled a resting order "
                            f"(ID: {_oid[:8]}…) left behind by the failed "
                            f"request above — it can no longer fill as a "
                            f"ghost position."
                        )
                        logger.warning(
                            "orphan_order_cancelled",
                            extra={"event": "orphan_order_cancelled", "symbol": symbol, "order_id": _oid},
                        )
            except Exception as _ce:
                _record_flow(
                    **flow_base, event_type="orphan_sweep_failed",
                    status="unknown", message=str(_ce), is_issue=True,
                )
                logger.warning("orphan_order_sweep_failed: %s", _ce)

            return None

    def _wait_for_fill(
        self,
        order_id: str,
        max_wait: Optional[int] = None,
        limit_price: Optional[float] = None,
        step_to_price: Optional[float] = None,
        side: str = "buy",
        symbol: Optional[str] = None,
        qty: Optional[int] = None,
        allow_market_fallback: bool = False,
        position_intent: Optional[str] = None,
        attempt_id: Optional[str] = None,
        order_context: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Poll order status until filled or rejected.
        Returns the order dict with confirmed_fill_price set, or None.

        BOUNDED FILL LOGIC:
        - Paper and live limits can step toward the supplied price after 2s.
          A marketable limit improves execution chances; it cannot guarantee a fill.
        - Wait 10s paper / 15s live by default, or a bounded caller override.
        - Confirm cancellation and preserve actual partial fills on timeout.
        - Paper market fallback requires explicit emergency-exit permission;
          buy-to-open entries never chase an unfilled limit at market.
        """
        context = order_context or {}
        attempt_id = attempt_id or uuid.uuid4().hex
        flow_base = {
            "attempt_id": attempt_id,
            "order_id": order_id,
            "contract_symbol": symbol,
            "ticker": context.get("ticker"),
            "strategy_id": context.get("strategy_id"),
            "candidate_id": context.get("candidate_id"),
            "intent_id": context.get("intent_id"),
            "side": side,
            "position_intent": position_intent,
            "requested_qty": qty,
            "limit_price": limit_price,
            "linked_trade_id": context.get("trade_id"),
        }
        if not order_id or order_id == "paper_simulated":
            return None

        # Detect paper vs live from current settings (not frozen URL) so a mode
        # switch between bot restarts is reflected immediately.
        from config import get_settings as _gs
        is_paper = _gs().get("paper_trading", "paper" in self.base.lower())
        # FIX 2026-07-31 (profitability audit): paper used to wait a flat 10s at
        # the mid-price limit, then cancel and fire a full MARKET order — no
        # intermediate step. Live already does better (steps mid->ask/bid at 5s
        # before ever going to market). Research on options execution is
        # consistent that market orders should be a last resort, not a 10-second
        # default — extending paper's wait to 20s gives the stepped limit (added
        # below) a real chance to fill before falling back to market.
        # ``max_wait`` existed but was previously ignored.  Entry callers can
        # now keep the exact reviewed contract working through most of the
        # next one-minute bar.  Bound the value so a synchronous scanner tick
        # can never hang indefinitely.
        requested_wait = int(max_wait or 0)
        effective_wait = requested_wait if requested_wait > 0 else (10 if is_paper else 15)
        effective_wait = max(5, min(effective_wait, 60))

        # Step-up threshold: on live, after this many seconds without a fill,
        # modify the order's limit price from mid up to the ask.
        _STEP_UP_AFTER_SECS = 2
        _stepped_up = False
        _last_status = None

        terminal_states = {"filled", "expired", "canceled", "cancelled", "rejected"}
        for i in range(effective_wait):
            # Step toward the supplied executable price; a fill is not guaranteed.
            _is_buy  = side.lower() == "buy"
            _step_ok = (
                step_to_price is not None
                and (
                    (_is_buy  and step_to_price > (limit_price or 0)) or  # ask > mid
                    (not _is_buy and step_to_price < (limit_price or float("inf")))  # bid < mid
                )
            )
            # FIX 2026-07-31: was "not is_paper" only — live got the gradual
            # mid->ask/bid step, paper went straight from mid to a full market
            # order at 10s with no intermediate step. Paper now gets the same
            # proven step logic live already uses, instead of a separate,
            # cruder fallback path.
            if (not _stepped_up and _step_ok and i == _STEP_UP_AFTER_SECS):
                try:
                    _previous_order_id = order_id
                    _replacement = self._patch(
                        f"{self.base}/v2/orders/{order_id}",
                        {"limit_price": str(round(step_to_price, 2))},
                    )
                    # Alpaca implements PATCH /orders/{id} as an order
                    # replacement.  The old order becomes ``replaced`` and a
                    # NEW order ID carries the working/filled order.  Keep
                    # polling that new ID; otherwise we watch the dead parent,
                    # misread ``replaced`` as still working, and can submit
                    # repeated exit attempts while the real child order is
                    # invisible to the bot.
                    _replacement_order_id = str(
                        (_replacement or {}).get("id")
                        or (_replacement or {}).get("order_id")
                        or order_id
                    )
                    if _replacement_order_id != order_id:
                        order_id = _replacement_order_id
                        flow_base = {
                            **flow_base,
                            "order_id": order_id,
                            "parent_order_id": _previous_order_id,
                        }
                    _stepped_up = True
                    _record_flow(
                        **{**flow_base, "limit_price": step_to_price},
                        event_type="price_step", status="replaced",
                        message=f"Limit stepped to {step_to_price:.2f}",
                    )
                    if _is_buy:
                        log_event("INFO", "order",
                                  f"⬆️ [{order_id[:8]}…] Mid-price buy not filled after "
                                  f"{_STEP_UP_AFTER_SECS}s — stepping UP to ask "
                                  f"${step_to_price:.2f}.")
                        logger.info("order_step_up mid=%.4f ask=%.4f order=%s",
                                    limit_price or 0, step_to_price, order_id)
                    else:
                        log_event("INFO", "order",
                                  f"⬇️ [{order_id[:8]}…] Mid-price sell not filled after "
                                  f"{_STEP_UP_AFTER_SECS}s — stepping DOWN to bid "
                                  f"${step_to_price:.2f}.")
                        logger.info("order_step_down mid=%.4f bid=%.4f order=%s",
                                    limit_price or 0, step_to_price, order_id)
                except Exception as _pe:
                    logger.warning("order_step_failed order=%s: %s", order_id, _pe)
                    _record_flow(
                        **flow_base, event_type="price_step_failed",
                        status="working", message=str(_pe), is_issue=True,
                    )

            try:
                order = self._get(f"{self.base}/v2/orders/{order_id}")
                status = order.get("status", "")
                if status != _last_status:
                    _record_flow(
                        **flow_base, event_type="broker_status", status=status,
                        filled_qty=int(float(order.get("filled_qty") or 0)),
                        message=f"Alpaca status changed to {status or 'unknown'}",
                    )
                    _last_status = status
                logger.debug("Order %s status: %s", order_id, status)
                if status == "filled":
                    filled_price = float(order.get("filled_avg_price") or 0)
                    actual_qty = float(order.get("filled_qty") or 0)
                    if not (math.isfinite(filled_price) and filled_price > 0
                            and math.isfinite(actual_qty) and actual_qty > 0 and actual_qty.is_integer()):
                        raise ValueError("Broker fill is missing a valid execution price or quantity")
                    # Log mid-price improvement vs worst-case (ask for buys, bid for sells).
                    if side.lower() == "buy":
                        _saved_per_contract = (step_to_price or filled_price) - filled_price
                        _fill_note = (
                            f" (filled at mid — saved ${_saved_per_contract:.2f}/contract vs ask)"
                            if _saved_per_contract > 0.005 else ""
                        )
                    else:
                        _saved_per_contract = filled_price - (step_to_price or filled_price)
                        _fill_note = (
                            f" (filled at mid — saved ${_saved_per_contract:.2f}/contract vs bid)"
                            if _saved_per_contract > 0.005 else ""
                        )
                    log_event("INFO", "order",
                              f"✅ Order filled @ ${filled_price:.2f}{_fill_note} — position recorded.")
                    logger.info("Order %s filled @ $%.4f", order_id, filled_price)
                    order["confirmed_fill_price"] = filled_price
                    # FIX 2026-07-20 (Alpaca fills audit): always report the
                    # REAL filled_qty, falling back to the requested qty only
                    # if Alpaca's response omits it — "filled" should mean the
                    # full requested qty, but callers should read this field
                    # rather than assume it.
                    order["filled_qty"] = int(actual_qty)
                    order["partial_fill"] = False
                    _record_flow(
                        **flow_base, event_type="filled", status="filled",
                        filled_qty=order["filled_qty"], fill_price=filled_price,
                        message="Alpaca confirmed the fill",
                    )
                    return order
                if status in terminal_states:
                    # FIX 2026-07-20 (Alpaca fills audit): an order can reach a
                    # terminal state (canceled/expired/etc.) AFTER having
                    # partially filled — e.g. Alpaca cancels the remainder at
                    # day-end. Previously this branch returned None regardless,
                    # which meant a REAL partial position at the broker was
                    # completely invisible to the bot. Surface it instead.
                    if float(order.get("filled_qty") or 0) > 0 and not (
                        math.isfinite(float(order.get("filled_avg_price") or 0))
                        and float(order.get("filled_avg_price") or 0) > 0
                    ):
                        return None  # Recovery retains the fill until its real price arrives.
                    _partial = _extract_partial_fill(order, None)
                    if _partial:
                        log_event(
                            "WARNING", "order",
                            f"🟡 Order ended '{status}' but {_partial['filled_qty']} "
                            f"contract(s) already filled @ "
                            f"${_partial['confirmed_fill_price']:.2f} — recording "
                            f"the REAL partial position, not discarding it."
                        )
                        logger.warning(
                            "partial_fill_terminal: order=%s status=%s filled_qty=%s",
                            order_id, status, _partial["filled_qty"],
                        )
                        _record_flow(
                            **flow_base, event_type="partial_filled", status=status,
                            filled_qty=_partial["filled_qty"],
                            fill_price=_partial["confirmed_fill_price"],
                            message=f"Order ended {status} after a partial fill",
                            is_issue=True,
                        )
                        return _partial
                    log_event("WARNING", "order",
                              f"⚠️ Order ended with status '{status}' — no position opened.")
                    logger.warning("Order %s ended with status: %s", order_id, status)
                    _record_flow(
                        **flow_base, event_type="terminal_no_fill", status=status,
                        message=f"Order ended {status} without a fill", is_issue=True,
                    )
                    return None
            except Exception as e:
                logger.warning("Status poll failed for %s: %s", order_id, e)
                if i == effective_wait - 1:
                    _record_flow(
                        **flow_base, event_type="status_poll_error",
                        status="unknown", message=str(e), is_issue=True,
                    )
            time.sleep(1)

        if is_paper:
            # Cancel the working remainder and verify its final broker status.
            # Only the explicit emergency-exit branch below may submit a market order.
            log_event("INFO", "order",
                      f"📝 Paper limit order pending after {effective_wait}s — "
                      f"requesting cancellation and checking for fills.")
            cancelled = False
            try:
                cancelled = self.cancel_order(order_id)
                _record_flow(
                    **flow_base, event_type="cancel_requested",
                    status="requested" if cancelled else "cancel_unconfirmed",
                    message="Paper limit order cancellation requested; checking final fill status",
                    is_issue=not bool(cancelled),
                )
            except Exception as _ce:
                logger.warning("paper_limit_cancel_failed order=%s: %s", order_id, _ce)
                _record_flow(
                    **flow_base, event_type="cancel_failed", status="working",
                    message=str(_ce), is_issue=True,
                )

            # FIX 2026-07-20 (Alpaca fills audit): the original limit order may
            # have PARTIALLY filled before we cancelled it — cancelling only
            # cancels the unfilled remainder, the filled portion is a REAL
            # position at the broker. Previously this code unconditionally
            # submitted a market order for the FULL original qty, which meant
            # a partial fill + a full-size market fill could double up the
            # position at the broker while the DB only ever recorded the
            # market order's (smaller, wrong) size. Read back the cancelled
            # order's actual filled_qty and only submit the REMAINDER.
            _orig_filled_qty   = 0
            _orig_filled_price = None
            _orig_final: dict = {}
            _orig_terminal = False
            _orig_status = "unknown"

            # A successful DELETE only means Alpaca accepted the cancellation
            # request.  It does NOT prove the order stopped working.  Confirm
            # a terminal broker status before submitting a replacement, or the
            # original limit and market fallback can both fill and double the
            # intended position.
            for _cancel_check in range(5):
                try:
                    _orig_final = self._get(f"{self.base}/v2/orders/{order_id}")
                    _orig_status = str(_orig_final.get("status") or "unknown").lower()
                    _orig_filled_qty = int(float(_orig_final.get("filled_qty") or 0))
                    _orig_filled_price = (
                        float(_orig_final.get("filled_avg_price") or 0) or None
                    )
                    if _orig_status in terminal_states:
                        _orig_terminal = True
                        break
                except Exception as _ge:
                    logger.warning(
                        "paper_orig_order_refetch_failed order=%s check=%s: %s",
                        order_id, _cancel_check + 1, _ge,
                    )
                if _cancel_check < 4:
                    time.sleep(1)

            if not _orig_terminal:
                log_event(
                    "CRITICAL", "order",
                    f"🔴 [{symbol}] Original limit order cancellation was not "
                    f"confirmed (broker status: {_orig_status}). Market fallback was "
                    f"BLOCKED to prevent a duplicate fill. Manual broker review required."
                )
                logger.critical(
                    "paper_fallback_blocked_cancel_unconfirmed: order=%s status=%s "
                    "cancel_request_accepted=%s filled_qty=%s",
                    order_id, _orig_status, cancelled, _orig_filled_qty,
                )
                _record_flow(
                    **flow_base,
                    event_type="fallback_blocked_cancel_unconfirmed",
                    status=_orig_status,
                    filled_qty=_orig_filled_qty or None,
                    fill_price=_orig_filled_price,
                    message=(
                        "Market fallback blocked because the original order was still "
                        f"working or its cancellation could not be confirmed ({_orig_status})"
                    ),
                    is_issue=True,
                )
                return None

            if _orig_filled_qty > 0 and not (
                _orig_filled_price and math.isfinite(_orig_filled_price) and _orig_filled_price > 0
            ):
                return None
            if _orig_filled_qty > 0:
                log_event(
                    "WARNING", "order",
                    f"🟡 [{symbol}] {_orig_filled_qty} contract(s) already filled "
                    f"@ ${_orig_filled_price or 0:.2f} before cancel — preserving "
                    f"the actual filled quantity."
                )
                logger.warning(
                    "paper_partial_before_cancel: order=%s filled_qty=%s requested=%s",
                    order_id, _orig_filled_qty, qty,
                )

            _remaining_qty = (qty - _orig_filled_qty) if qty else qty

            if _remaining_qty is not None and _remaining_qty <= 0 and _orig_filled_qty > 0:
                # The original limit order actually fully filled right before
                # our cancel landed (a timing race) — nothing left to order.
                _orig_final["confirmed_fill_price"] = _orig_filled_price or limit_price or 0
                _orig_final["filled_qty"]  = _orig_filled_qty
                _orig_final["status"]      = "filled"
                _orig_final["partial_fill"] = False
                log_event("INFO", "order",
                          f"✅ [{symbol}] Original limit order fully filled just before "
                          f"cancel took effect — no market fallback needed.")
                _record_flow(
                    **flow_base, event_type="filled", status="filled",
                    filled_qty=_orig_filled_qty,
                    fill_price=_orig_filled_price or limit_price or 0,
                    message="Original limit order filled before cancellation",
                )
                return _orig_final

            if position_intent == "buy_to_open":
                # Entry discipline: never turn a stale/unfilled option limit
                # into an uncapped market buy.  The contract-selection quote
                # can come from a different feed than Alpaca's simulator; this
                # week that fallback paid 7%-19% above the reviewed ask and
                # converted otherwise-positive setups into losses.  A missed
                # entry is safer and more truthful than chasing it at any
                # price.  Real partial fills are still surfaced so the bot can
                # manage the position that actually exists.
                if _orig_filled_qty > 0:
                    _record_flow(
                        **flow_base, event_type="partial_filled",
                        status="partially_filled", filled_qty=_orig_filled_qty,
                        fill_price=_orig_filled_price or limit_price or 0,
                        message=(
                            "Original entry partially filled; unfilled remainder "
                            "was not chased with a market order"
                        ),
                        is_issue=True,
                    )
                    return {
                        "id": order_id,
                        "status": "partially_filled",
                        "confirmed_fill_price": _orig_filled_price or limit_price or 0,
                        "filled_qty": _orig_filled_qty,
                        "partial_fill": True,
                    }
                log_event(
                    "WARNING", "order",
                    f"🟡 [{symbol}] Entry limit did not fill within "
                    f"{effective_wait}s — setup skipped rather than chased at market.",
                )
                _record_flow(
                    **flow_base, event_type="entry_expired_no_fill",
                    status=_orig_status, filled_qty=0,
                    message="Entry canceled without fill; market chase disabled",
                )
                return None

            if not allow_market_fallback:
                if _orig_filled_qty > 0:
                    _record_flow(
                        **flow_base, event_type="partial_filled",
                        status="partially_filled", filled_qty=_orig_filled_qty,
                        fill_price=_orig_filled_price or limit_price or 0,
                        message="Limit partially filled; uncapped market fallback disabled",
                        is_issue=True,
                    )
                    return {
                        "id": order_id,
                        "status": "partially_filled",
                        "confirmed_fill_price": _orig_filled_price or limit_price or 0,
                        "filled_qty": _orig_filled_qty,
                        "partial_fill": True,
                    }
                log_event(
                    "WARNING", "order",
                    f"🟡 [{symbol}] Limit did not fill within {effective_wait}s — "
                    f"uncapped market fallback is disabled; will re-evaluate the live quote.",
                )
                _record_flow(
                    **flow_base, event_type="limit_expired_no_fill",
                    status=_orig_status, filled_qty=0,
                    message="Limit canceled without fill; uncapped market fallback disabled",
                )
                return None

            if symbol and _remaining_qty:
                try:
                    mkt_payload = {
                        "symbol":        symbol,
                        "qty":           str(_remaining_qty),
                        "side":          side,
                        "type":          "market",
                        "time_in_force": "day",
                    }
                    if position_intent:
                        mkt_payload["position_intent"] = position_intent
                    mkt_order    = self._post(f"{self.base}/v2/orders", mkt_payload)
                    mkt_order_id = mkt_order.get("id", "")
                    fallback_base = {
                        **flow_base,
                        "order_id": mkt_order_id,
                        "parent_order_id": order_id,
                        "order_type": "market",
                        "requested_qty": _remaining_qty,
                    }
                    _record_flow(
                        **fallback_base, event_type="fallback_acknowledged",
                        status=mkt_order.get("status") or "accepted",
                        message="Alpaca acknowledged the market fallback",
                    )
                    log_event("INFO", "order",
                              f"📤 [{symbol}] Market fallback sent for {_remaining_qty} "
                              f"contract(s) (ID: {mkt_order_id[:8]}…). Waiting for fill…")
                    # Poll up to 30s for the market fill — paper markets fill fast
                    for _ in range(30):
                        time.sleep(1)
                        try:
                            mkt_status = self._get(f"{self.base}/v2/orders/{mkt_order_id}")
                            if mkt_status.get("status") == "filled":
                                _mkt_filled_qty = int(float(
                                    mkt_status.get("filled_qty") or 0
                                ))
                                _mkt_price = float(
                                    mkt_status.get("filled_avg_price") or 0
                                )
                                if _mkt_filled_qty <= 0 or not math.isfinite(_mkt_price) or _mkt_price <= 0:
                                    raise ValueError("Market fill missing confirmed quantity/price")
                                # Weighted-average price across the original
                                # partial fill (if any) + this market fill, so
                                # confirmed_fill_price reflects the REAL blended
                                # cost basis of the combined position.
                                _total_qty = _orig_filled_qty + _mkt_filled_qty
                                if _orig_filled_qty > 0 and _orig_filled_price and _total_qty > 0:
                                    filled_price = (
                                        (_orig_filled_qty * _orig_filled_price)
                                        + (_mkt_filled_qty * _mkt_price)
                                    ) / _total_qty
                                else:
                                    filled_price = _mkt_price
                                log_event("INFO", "order",
                                          f"✅ Market fallback filled @ ${_mkt_price:.2f} "
                                          f"(blended position price ${filled_price:.2f} "
                                          f"across {_total_qty} contract(s))")
                                logger.info("paper_market_fill: order=%s fill=%.4f total_qty=%s",
                                            mkt_order_id, filled_price, _total_qty)
                                mkt_status["confirmed_fill_price"] = filled_price
                                mkt_status["filled_qty"] = _total_qty
                                mkt_status["partial_fill"] = _orig_filled_qty > 0
                                _record_flow(
                                    **fallback_base, event_type="filled", status="filled",
                                    filled_qty=_total_qty, fill_price=filled_price,
                                    message="Market fallback filled",
                                )
                                return mkt_status
                            if mkt_status.get("status") in terminal_states:
                                break
                        except Exception:
                            pass
                except Exception as _me:
                    logger.warning("paper_market_fallback_failed: %s", _me)
                    _record_flow(
                        **flow_base, event_type="fallback_unconfirmed",
                        status="failed", message=str(_me), is_issue=True,
                    )

            # FIX 2026-07-17: this used to fabricate a "confirmed" fill here even
            # though nothing actually filled — the dict's own status field said
            # "paper_market_fallback_failed" but callers only check truthiness,
            # not status, so a canceled/never-filled order got recorded as a
            # real open trade anyway (confirmed live: XLE trade #146 — Alpaca's
            # order history showed the limit canceled with NO fill ever, yet
            # our DB had a full "open position" at that canceled price/size).
            # Live mode already returns None on an unconfirmed fill (see the
            # `else` branch below) — paper mode must do the same instead of
            # ever inventing a trade that never happened.
            #
            # FIX 2026-07-20 (Alpaca fills audit): "market fallback didn't
            # confirm" is NOT the same as "nothing filled" if the ORIGINAL
            # limit order had a partial fill before we cancelled it — that
            # partial fill is still a real position at the broker and must
            # not be dropped just because the follow-up market order failed.
            if _orig_filled_qty > 0:
                log_event(
                    "WARNING", "order",
                    f"🟡 [{symbol}] Market fallback failed, but {_orig_filled_qty} "
                    f"contract(s) from the original order already filled @ "
                    f"${_orig_filled_price or 0:.2f} — recording that REAL partial "
                    f"position instead of discarding it."
                )
                logger.warning(
                    "paper_partial_fill_market_fallback_failed: order=%s filled_qty=%s",
                    order_id, _orig_filled_qty,
                )
                _record_flow(
                    **flow_base, event_type="partial_filled",
                    status="partially_filled", filled_qty=_orig_filled_qty,
                    fill_price=_orig_filled_price or limit_price or 0,
                    message="Original order partially filled; market fallback did not complete",
                    is_issue=True,
                )
                return {
                    "id": order_id,
                    "status": "partially_filled",
                    "confirmed_fill_price": _orig_filled_price or limit_price or 0,
                    "filled_qty": _orig_filled_qty,
                    "partial_fill": True,
                }

            log_event("ERROR", "order",
                      f"🔴 [{symbol}] Market fallback did not confirm filled — "
                      f"no position recorded. Will look for the next setup.")
            logger.error("paper_market_fallback_unconfirmed: order=%s — returning None, no phantom trade", order_id)
            _record_flow(
                **flow_base, event_type="fallback_unconfirmed",
                status="unconfirmed", message="Market fallback did not confirm a fill",
                is_issue=True,
            )
            return None
        else:
            # Live: order didn't fill in 30s — cancel to prevent ghost positions.
            log_event("WARNING", "order",
                      f"⚠️ Live order did not fill in {effective_wait}s — cancelling "
                      f"to prevent ghost position. Will look for next setup.")
            logger.error("Order %s timed out waiting for fill after %ds", order_id, effective_wait)
            _record_flow(
                **flow_base, event_type="live_timeout", status="timed_out",
                message=f"Live order did not fill within {effective_wait} seconds",
                is_issue=True,
            )
            cancelled = False
            try:
                cancelled = self.cancel_order(order_id)
                _record_flow(
                    **flow_base, event_type="cancel_requested",
                    status="requested" if cancelled else "cancel_unconfirmed",
                    message="Live timed-out order cancellation requested",
                    is_issue=not bool(cancelled),
                )
                if cancelled:
                    log_event("WARNING", "order",
                              f"🟡 Timed-out order ({order_id[:8]}…) cancelled.")
                    logger.warning(
                        "timed_out_order_cancelled",
                        extra={"event": "timed_out_order_cancelled", "order_id": order_id},
                    )
            except Exception as _ce:
                logger.warning("Failed to cancel timed-out order %s: %s", order_id, _ce)
                _record_flow(
                    **flow_base, event_type="cancel_failed", status="timed_out",
                    message=str(_ce), is_issue=True,
                )

            # FIX 2026-07-20 (Alpaca fills audit): cancelling a live order only
            # cancels the UNFILLED remainder — if it had partially filled
            # before the cancel landed, that fill is a real position at the
            # broker. Re-fetch the order once more to check, instead of
            # unconditionally returning None (which previously made a real
            # partial live position invisible to the bot).
            _final: dict = {}
            _final_status = "unknown"
            _cancel_terminal = False
            for _cancel_check in range(5):
                try:
                    _final = self._get(f"{self.base}/v2/orders/{order_id}")
                    _final_status = str(_final.get("status") or "unknown").lower()
                    if _final_status in terminal_states:
                        _cancel_terminal = True
                        break
                except Exception as _fe:
                    logger.warning(
                        "live_timeout_refetch_failed order=%s check=%s: %s",
                        order_id, _cancel_check + 1, _fe,
                    )
                if _cancel_check < 4:
                    time.sleep(1)

            if not _cancel_terminal:
                log_event(
                    "CRITICAL", "order",
                    f"🔴 Live order {order_id[:8]}… timed out, but Alpaca has not "
                    f"confirmed cancellation (status: {_final_status}). Check the broker; "
                    f"the order may still be working."
                )
                _record_flow(
                    **flow_base,
                    event_type="cancel_unconfirmed",
                    status=_final_status,
                    filled_qty=int(float(_final.get("filled_qty") or 0)) or None,
                    fill_price=(
                        float(_final.get("filled_avg_price") or 0) or None
                    ),
                    message=(
                        "Live timeout cancellation was not confirmed; the original "
                        f"order may still be working ({_final_status})"
                    ),
                    is_issue=True,
                )
                return None

            if _final_status == "filled":
                _filled_price = float(
                    _final.get("filled_avg_price") or 0
                )
                if not math.isfinite(_filled_price) or _filled_price <= 0 or float(_final.get("filled_qty") or 0) <= 0:
                    return None
                _final["confirmed_fill_price"] = _filled_price
                _final["filled_qty"] = int(float(_final.get("filled_qty") or qty or 0))
                _final["partial_fill"] = False
                _record_flow(
                    **flow_base, event_type="filled", status="filled",
                    filled_qty=_final["filled_qty"], fill_price=_filled_price,
                    message="Live order filled while timeout cancellation was pending",
                )
                return _final

            if float(_final.get("filled_qty") or 0) > 0 and not (
                math.isfinite(float(_final.get("filled_avg_price") or 0)) and float(_final.get("filled_avg_price") or 0) > 0
            ):
                return None
            _partial = _extract_partial_fill(_final, None)
            if _partial:
                log_event(
                    "WARNING", "order",
                    f"🟡 Live order timed out and was cancelled, but "
                    f"{_partial['filled_qty']} contract(s) already filled @ "
                    f"${_partial['confirmed_fill_price']:.2f} before cancel — "
                    f"recording the REAL partial position."
                )
                logger.warning(
                    "partial_fill_live_timeout: order=%s filled_qty=%s",
                    order_id, _partial["filled_qty"],
                )
                _record_flow(
                    **flow_base, event_type="partial_filled",
                    status=_final_status, filled_qty=_partial["filled_qty"],
                    fill_price=_partial["confirmed_fill_price"],
                    message="Live order partially filled before timeout cancellation",
                    is_issue=True,
                )
                return _partial
            _record_flow(
                **flow_base, event_type="terminal_no_fill", status=_final_status,
                message="Live timed-out order ended without a confirmed fill",
                is_issue=True,
            )
            return None
