"""Tradier brokerage account and confirmed single-leg option execution.

An HTTP 200 from Tradier only acknowledges an order request; it is not a fill.
This mixin returns a dict only after Tradier reports a real full or partial
execution, matching the safety contract used by the rest of the bot.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from time import monotonic
from typing import Optional

import requests

from database import log_event, record_broker_order_event

logger = logging.getLogger("celo_trader.broker")

_WORKING_STATUSES = {
    "open", "pending", "partially_filled", "accepted_for_bidding", "held",
}
_NO_FILL_TERMINAL = {"expired", "canceled", "cancelled", "rejected", "error"}


def _items(value) -> list[dict]:
    """Normalize Tradier's one-object-or-array JSON representation."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _record_flow(**event) -> None:
    """Write execution evidence without making telemetry load-bearing."""
    try:
        record_broker_order_event(broker="tradier", **event)
    except Exception:
        logger.warning("tradier_broker_order_event_write_failed", exc_info=True)


def _underlying_from_occ(option_symbol: str) -> str:
    match = re.match(r"^([A-Z./]+?)\d{6}[CP]\d{8}$", str(option_symbol or "").upper())
    return match.group(1) if match else ""


class TradierExecutionMixin:
    """Account state, positions, orders, and confirmed option execution."""

    last_rejection_reason: Optional[str] = None

    # ── Account state ──────────────────────────────────────────────────────

    def get_account(self) -> dict:
        if not getattr(self, "api_key", "") or not getattr(self, "account_id", ""):
            raise RuntimeError("Tradier credentials are incomplete")
        payload = self._get(f"/accounts/{self.account_id}/balances")
        balances = payload.get("balances") if isinstance(payload, dict) else None
        if not isinstance(balances, dict):
            raise RuntimeError("Tradier returned no usable account balances")
        return {
            "id": str(self.account_id),
            "equity": float(balances.get("total_equity") or 0),
            "buying_power": float(
                balances.get("stock_buying_power")
                or balances.get("option_buying_power")
                or balances.get("total_cash")
                or 0
            ),
            "cash": float(balances.get("total_cash") or 0),
            "options_buying_power": float(
                balances.get("option_buying_power")
                or balances.get("total_cash")
                or 0
            ),
        }

    def get_positions(self) -> list[dict]:
        payload = self._get(f"/accounts/{self.account_id}/positions")
        positions = payload.get("positions") if isinstance(payload, dict) else None
        rows = _items(positions.get("position") if isinstance(positions, dict) else None)
        normalized: list[dict] = []
        for row in rows:
            quantity = int(float(row.get("quantity") or 0))
            cost_basis = float(row.get("cost_basis") or 0)
            symbol = str(row.get("symbol") or row.get("option_symbol") or "")
            avg_entry_price = (
                abs(cost_basis) / (abs(quantity) * 100)
                if quantity and re.search(r"\d{6}[CP]\d{8}$", symbol)
                else (abs(cost_basis) / abs(quantity) if quantity else 0)
            )
            normalized.append({
                **row,
                "symbol": symbol,
                "qty": quantity,
                "quantity": quantity,
                "avg_entry_price": avg_entry_price,
            })
        return normalized

    # ── Order reads and mutations ──────────────────────────────────────────

    def get_order(self, order_id: str) -> dict:
        payload = self._get(
            f"/accounts/{self.account_id}/orders/{order_id}",
            {"includeTags": "true"},
        )
        order = payload.get("order") if isinstance(payload, dict) else None
        return order if isinstance(order, dict) else {}

    def get_orders(self) -> list[dict]:
        payload = self._get(
            f"/accounts/{self.account_id}/orders",
            {"limit": 1000, "includeTags": "true"},
        )
        orders = payload.get("orders") if isinstance(payload, dict) else None
        return _items(orders.get("order") if isinstance(orders, dict) else None)

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        rows = [
            order for order in self.get_orders()
            if str(order.get("status") or "").lower() in _WORKING_STATUSES
        ]
        if symbol:
            rows = [
                order for order in rows
                if str(order.get("option_symbol") or order.get("symbol") or "") == symbol
            ]
        return rows

    def _change_order(
        self,
        order_id: str,
        *,
        order_type: str,
        duration: str = "day",
        price: Optional[float] = None,
    ) -> bool:
        payload = {"type": order_type, "duration": duration}
        if price is not None:
            payload["price"] = str(round(float(price), 2))
        response = requests.put(
            f"{self.base}/accounts/{self.account_id}/orders/{order_id}",
            headers=self.headers,
            data=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True

    def cancel_order(self, order_id: str) -> bool:
        if not order_id:
            return False
        try:
            response = requests.delete(
                f"{self.base}/accounts/{self.account_id}/orders/{order_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("tradier_order_cancel_failed order=%s: %s", order_id, exc)
            return False

        # Tradier recommends checking status after the 200 cancel response.
        for attempt in range(5):
            try:
                status = str(self.get_order(order_id).get("status") or "").lower()
                if status in {"canceled", "cancelled", "expired", "rejected", "error"}:
                    return True
                if status == "filled":
                    return False
            except Exception:
                logger.warning("tradier_cancel_status_check_failed", exc_info=True)
            if attempt < 4:
                time.sleep(1)
        return False

    # ── Confirmed option execution ─────────────────────────────────────────

    def place_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        step_to_price: Optional[float] = None,
        max_acceptable_price: Optional[float] = None,
        allow_market_fallback: bool = False,
        position_intent: Optional[str] = None,
        order_context: Optional[dict] = None,
        max_wait_seconds: Optional[int] = None,
        price_authority: str = "tradier",
    ) -> Optional[dict]:
        """Submit one option order and return only a broker-confirmed fill."""
        del price_authority  # Tradier is both quote and execution authority.
        attempt_id = uuid.uuid4().hex
        context = order_context or {}
        intent_id = str(context.get("intent_id") or "").strip()
        normalized_side = str(position_intent or "").strip().lower()
        if normalized_side not in {
            "buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close",
        }:
            normalized_side = "buy_to_open" if str(side).lower() == "buy" else "sell_to_close"
        underlying = str(context.get("ticker") or _underlying_from_occ(symbol)).upper()
        flow_base = {
            "attempt_id": attempt_id,
            "contract_symbol": symbol,
            "ticker": context.get("ticker") or underlying,
            "strategy_id": context.get("strategy_id"),
            "candidate_id": context.get("candidate_id"),
            "intent_id": intent_id or None,
            "side": side,
            "position_intent": normalized_side,
            "requested_qty": qty,
            "order_type": order_type,
            "limit_price": limit_price,
            "linked_trade_id": context.get("trade_id"),
            "paper": "sandbox" in str(getattr(self, "base", "")).lower(),
        }
        reference_bid = float(context.get("quote_bid") or 0)
        reference_ask = float(context.get("quote_ask") or 0)
        reference_mid = float(context.get("quote_mid") or 0)
        natural_reference = (
            reference_ask if normalized_side.startswith("buy") else reference_bid
        )
        if reference_bid > 0 or reference_ask > 0:
            _record_flow(
                **{**flow_base, "limit_price": natural_reference or limit_price},
                event_type="authoritative_quote",
                status="quoted",
                latency_ms=context.get("quote_latency_ms"),
                message=(
                    f"Tradier authoritative quote bid={reference_bid:.2f} "
                    f"ask={reference_ask:.2f} mid={reference_mid:.2f}; "
                    f"working limit={float(limit_price or 0):.2f}"
                ),
            )
        if not getattr(self, "api_key", "") or not getattr(self, "account_id", ""):
            self.last_rejection_reason = "Tradier credentials are incomplete"
            _record_flow(
                **flow_base, event_type="not_sent_missing_credentials",
                status="not_sent", message=self.last_rejection_reason, is_issue=True,
            )
            return None
        if not underlying:
            self.last_rejection_reason = "Could not derive the option underlying symbol"
            _record_flow(
                **flow_base, event_type="submission_error", status="rejected",
                message=self.last_rejection_reason, is_issue=True,
            )
            return None

        self.last_rejection_reason = None
        tag = f"celo-{(intent_id or attempt_id)[:24]}"
        payload = {
            "class": "option",
            "symbol": underlying,
            "option_symbol": symbol,
            "side": normalized_side,
            "quantity": str(int(qty)),
            "type": order_type,
            "duration": "day",
            "tag": tag,
        }
        if order_type == "limit":
            if not limit_price or float(limit_price) <= 0:
                self.last_rejection_reason = "A positive limit price is required"
                _record_flow(
                    **flow_base, event_type="submission_error", status="rejected",
                    message=self.last_rejection_reason, is_issue=True,
                )
                return None
            payload["price"] = str(round(float(limit_price), 2))

        _record_flow(
            **flow_base, event_type="submit_attempt", status="sending",
            message=f"Sending {normalized_side} {qty} contract(s) to Tradier",
        )
        submit_started = monotonic()
        order_id = ""
        try:
            # Never blindly retry a POST: a lost acknowledgement after receipt
            # could duplicate a live order. Reconcile its unique tag instead.
            response = requests.post(
                f"{self.base}/accounts/{self.account_id}/orders",
                headers=self.headers,
                data=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json() if response.text and response.text.strip() else {}
            acknowledged = data.get("order") if isinstance(data, dict) else None
            order_id = str(acknowledged.get("id") or "") if isinstance(acknowledged, dict) else ""
            if not order_id:
                raise RuntimeError("Tradier acknowledged the request without an order ID")
        except Exception as exc:
            try:
                matching = [o for o in self.get_orders() if str(o.get("tag") or "") == tag]
                if len(matching) == 1:
                    order_id = str(matching[0].get("id") or "")
            except Exception:
                logger.warning("tradier_submit_reconciliation_failed", exc_info=True)
            if not order_id:
                self.last_rejection_reason = self._rejection_reason(exc)
                _record_flow(
                    **flow_base, event_type="submission_error", status="rejected",
                    message=self.last_rejection_reason, is_issue=True,
                    latency_ms=round((monotonic() - submit_started) * 1000, 1),
                )
                log_event(
                    "ERROR", "order",
                    f"🔴 [{symbol}] Tradier order rejected — {self.last_rejection_reason}. "
                    "No position recorded.",
                )
                return None

        _record_flow(
            **flow_base, event_type="acknowledged", order_id=order_id,
            status="accepted",
            latency_ms=round((monotonic() - submit_started) * 1000, 1),
            message="Tradier acknowledged the order; waiting for execution status",
        )
        log_event(
            "INFO", "order",
            f"📤 [{symbol}] Tradier accepted {normalized_side.upper()} {qty}× {symbol}. "
            "Waiting for a confirmed fill…",
        )
        confirmed = self._wait_for_tradier_fill(
            order_id=order_id, flow_base=flow_base, qty=int(qty), side=normalized_side,
            limit_price=limit_price, step_to_price=step_to_price,
            max_acceptable_price=max_acceptable_price,
            allow_market_fallback=allow_market_fallback,
            max_wait_seconds=max_wait_seconds,
        )
        if confirmed is None:
            return None
        confirmed_fill_price = float(
            confirmed.get("confirmed_fill_price")
            or confirmed.get("filled_avg_price")
            or 0
        )
        _record_flow(
            **{
                **flow_base,
                "limit_price": natural_reference or limit_price,
            },
            event_type="execution_summary",
            order_id=order_id,
            status="filled",
            filled_qty=int(float(confirmed.get("filled_qty") or qty or 0)),
            fill_price=confirmed_fill_price,
            latency_ms=round((monotonic() - submit_started) * 1000, 1),
            message=(
                "Tradier decision quote to Tradier confirmed fill; "
                f"working limit={float(limit_price or 0):.2f}"
            ),
        )
        confirmed["execution_attempt_id"] = attempt_id
        if intent_id:
            confirmed["order_intent_id"] = intent_id
        return confirmed

    def _wait_for_tradier_fill(
        self,
        *,
        order_id: str,
        flow_base: dict,
        qty: int,
        side: str,
        limit_price: Optional[float],
        step_to_price: Optional[float],
        max_acceptable_price: Optional[float],
        allow_market_fallback: bool,
        max_wait_seconds: Optional[int],
    ) -> Optional[dict]:
        wait_seconds = max(1, int(max_wait_seconds or 30))
        started = monotonic()
        stepped = False
        last_order: dict = {}

        while monotonic() - started < wait_seconds:
            try:
                last_order = self.get_order(order_id)
                normalized = self._confirmed_fill(last_order, requested_qty=qty)
                status = str(last_order.get("status") or "unknown").lower()
                if status == "filled":
                    _record_flow(
                        **flow_base, event_type="filled", order_id=order_id,
                        status=status, filled_qty=normalized["filled_qty"],
                        fill_price=normalized["confirmed_fill_price"],
                        latency_ms=round((monotonic() - started) * 1000, 1),
                        message="Tradier confirmed the order filled",
                    )
                    return normalized
                if status in _NO_FILL_TERMINAL:
                    if normalized["filled_qty"] > 0:
                        normalized["partial_fill"] = True
                        _record_flow(
                            **flow_base, event_type="partial_filled", order_id=order_id,
                            status=status, filled_qty=normalized["filled_qty"],
                            fill_price=normalized["confirmed_fill_price"],
                            message="Tradier confirmed a partial execution before termination",
                            is_issue=True,
                        )
                        return normalized
                    self.last_rejection_reason = str(
                        last_order.get("reason_description") or f"Tradier order ended {status}"
                    )
                    _record_flow(
                        **flow_base, event_type="terminal_no_fill", order_id=order_id,
                        status=status, message=self.last_rejection_reason, is_issue=True,
                    )
                    return None
            except Exception as exc:
                _record_flow(
                    **flow_base, event_type="status_poll_error", order_id=order_id,
                    status="unknown", message=str(exc), is_issue=True,
                )

            elapsed = monotonic() - started
            if (
                not stepped and step_to_price is not None and limit_price is not None
                and elapsed >= min(5, wait_seconds / 2)
            ):
                target = float(step_to_price)
                if side.startswith("buy") and max_acceptable_price is not None:
                    target = min(target, float(max_acceptable_price))
                if target > 0 and round(target, 2) != round(float(limit_price), 2):
                    try:
                        self._change_order(order_id, order_type="limit", price=target)
                        stepped = True
                        _record_flow(
                            **{**flow_base, "limit_price": target},
                            event_type="price_step", order_id=order_id, status="working",
                            message=f"Tradier working limit changed to {target:.2f}",
                        )
                    except Exception as exc:
                        stepped = True
                        _record_flow(
                            **flow_base, event_type="price_step_failed", order_id=order_id,
                            status="working", message=str(exc), is_issue=True,
                        )
            time.sleep(1)

        # Only urgent exits may convert the working order to market.
        if allow_market_fallback and side == "sell_to_close":
            try:
                if self._change_order(order_id, order_type="market"):
                    _record_flow(
                        **flow_base, event_type="market_fallback", order_id=order_id,
                        status="working", message="Urgent Tradier exit changed to market",
                        is_issue=True,
                    )
                    for _ in range(15):
                        last_order = self.get_order(order_id)
                        normalized = self._confirmed_fill(last_order, requested_qty=qty)
                        status = str(last_order.get("status") or "unknown").lower()
                        if status == "filled":
                            _record_flow(
                                **flow_base, event_type="filled", order_id=order_id,
                                status=status, filled_qty=normalized["filled_qty"],
                                fill_price=normalized["confirmed_fill_price"],
                                message="Tradier confirmed urgent market exit fill",
                            )
                            return normalized
                        if status in _NO_FILL_TERMINAL:
                            break
                        time.sleep(1)
            except Exception as exc:
                _record_flow(
                    **flow_base, event_type="fallback_unconfirmed", order_id=order_id,
                    status="unknown", message=str(exc), is_issue=True,
                )

        cancel_confirmed = self.cancel_order(order_id)
        try:
            last_order = self.get_order(order_id)
        except Exception:
            last_order = {}
        normalized = self._confirmed_fill(last_order, requested_qty=qty)
        status = str(last_order.get("status") or "unknown").lower()
        if normalized["filled_qty"] > 0:
            normalized["partial_fill"] = normalized["filled_qty"] < qty
            _record_flow(
                **flow_base,
                event_type="partial_filled" if normalized["partial_fill"] else "filled",
                order_id=order_id, status=status,
                filled_qty=normalized["filled_qty"],
                fill_price=normalized["confirmed_fill_price"],
                message="Tradier confirmed execution during timeout cancellation",
                is_issue=normalized["partial_fill"],
            )
            return normalized

        event_type = "terminal_no_fill" if cancel_confirmed else "cancel_unconfirmed"
        self.last_rejection_reason = (
            f"Tradier order timed out after {wait_seconds}s and was canceled"
            if cancel_confirmed
            else f"Tradier order timed out after {wait_seconds}s; cancellation is unconfirmed"
        )
        _record_flow(
            **flow_base, event_type=event_type, order_id=order_id, status=status,
            message=self.last_rejection_reason, is_issue=not cancel_confirmed,
        )
        return None

    @staticmethod
    def _confirmed_fill(order: dict, *, requested_qty: int) -> dict:
        filled_qty = int(float(order.get("exec_quantity") or order.get("filled_qty") or 0))
        fill_price = float(
            order.get("avg_fill_price") or order.get("filled_avg_price")
            or order.get("last_fill_price") or 0
        )
        return {
            **order,
            "id": str(order.get("id") or ""),
            "filled_qty": filled_qty,
            "filled_avg_price": fill_price,
            "confirmed_fill_price": fill_price,
            "partial_fill": 0 < filled_qty < int(requested_qty),
        }

    @staticmethod
    def _rejection_reason(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                body = response.json()
                errors = body.get("errors") if isinstance(body, dict) else None
                error = errors.get("error") if isinstance(errors, dict) else None
                if isinstance(error, list):
                    return "; ".join(str(item) for item in error)[:500]
                if error:
                    return str(error)[:500]
            except Exception:
                pass
        return str(exc)[:500] or type(exc).__name__

    # ── Emergency/manual position close ────────────────────────────────────

    def close_position(self, symbol: str) -> bool:
        position = next((p for p in self.get_positions() if p.get("symbol") == symbol), None)
        qty = abs(int(position.get("qty") or 0)) if position else 0
        if qty < 1:
            self.last_rejection_reason = "no matching Tradier position"
            return False
        fill = self.place_option_order(
            symbol=symbol, qty=qty, side="sell", order_type="market",
            position_intent="sell_to_close",
            order_context={"ticker": _underlying_from_occ(symbol)},
            max_wait_seconds=20,
        )
        return fill is not None

    def close_all_positions(self) -> bool:
        positions = [p for p in self.get_positions() if int(p.get("qty") or 0) > 0]
        results = [self.close_position(str(position.get("symbol") or "")) for position in positions]
        if all(results):
            log_event("WARNING", "broker.tradier", "🔴 Emergency Tradier close completed.")
            return True
        log_event(
            "CRITICAL", "broker.tradier",
            "🔴 Emergency Tradier close did not confirm every position. Manual review required.",
        )
        return False
