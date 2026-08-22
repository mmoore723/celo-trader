from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from broker.alpaca_orders import AlpacaOrdersMixin
from database.broker_order_flow import (
    get_broker_order_flow,
    link_broker_order_to_trade,
    record_broker_order_event,
)
from database.schema import _init_db_at
from trading.diagnostics.ghost_positions import _find_db_only_positions


class _PaperFallbackBroker(AlpacaOrdersMixin):
    base = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.get_calls = 0
        self.posted: list[dict] = []

    def _get(self, _url: str) -> dict:
        self.get_calls += 1
        if self.get_calls <= 10:
            return {"status": "new", "filled_qty": "0"}
        if self.get_calls == 11:
            return {"status": "canceled", "filled_qty": "0"}
        return {"status": "filled", "filled_qty": "2", "filled_avg_price": "1.24"}

    def _post(self, _url: str, payload: dict) -> dict:
        self.posted.append(payload)
        return {"id": "fallback-order", "status": "accepted"}

    def _patch(self, _url: str, _payload: dict) -> dict:
        return {}

    def cancel_order(self, _order_id: str) -> bool:
        return True


class _UnconfirmedCancelBroker(AlpacaOrdersMixin):
    base = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.posted: list[dict] = []

    def _get(self, _url: str) -> dict:
        return {"status": "new", "filled_qty": "0"}

    def _post(self, _url: str, payload: dict) -> dict:
        self.posted.append(payload)
        return {"id": "should-not-be-submitted", "status": "accepted"}

    def _patch(self, _url: str, _payload: dict) -> dict:
        return {}

    def cancel_order(self, _order_id: str) -> bool:
        return False


class _LiveUnconfirmedCancelBroker(_UnconfirmedCancelBroker):
    base = "https://api.alpaca.markets"


class _ReplacementFillBroker(AlpacaOrdersMixin):
    base = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.get_urls: list[str] = []
        self.cancelled: list[str] = []

    def _get(self, url: str) -> dict:
        self.get_urls.append(url)
        if url.endswith("replacement-order"):
            return {
                "id": "replacement-order",
                "status": "filled",
                "filled_qty": "2",
                "filled_avg_price": "1.31",
            }
        return {"id": "original-order", "status": "new", "filled_qty": "0"}

    def _patch(self, _url: str, _payload: dict) -> dict:
        return {"id": "replacement-order", "status": "new"}

    def cancel_order(self, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True


class _ExecutionQuoteBroker(AlpacaOrdersMixin):
    base = "https://paper-api.alpaca.markets"
    api_key = "test-key"

    def __init__(self) -> None:
        self.posted: list[dict] = []
        self.wait_kwargs: dict = {}
        self.quote_calls = 0

    def get_latest_option_quote(self, _symbol: str) -> dict:
        self.quote_calls += 1
        return {"bp": 1.20, "ap": 1.30}

    def _post(self, _url: str, payload: dict) -> dict:
        self.posted.append(payload)
        return {"id": "quoted-order", "status": "accepted"}

    def _wait_for_fill(self, _order_id: str, **kwargs) -> dict:
        self.wait_kwargs = kwargs
        return {"id": "quoted-order", "status": "filled", "filled_avg_price": "1.30"}


class _BoundedWorkingBroker(AlpacaOrdersMixin):
    base = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.get_calls = 0

    def _get(self, _url: str) -> dict:
        self.get_calls += 1
        # Five working polls, then cancellation confirmation.
        return {
            "status": "new" if self.get_calls <= 5 else "canceled",
            "filled_qty": "0",
        }

    def cancel_order(self, _order_id: str) -> bool:
        return True


class BrokerOrderExecutionTests(unittest.TestCase):
    def test_entry_honors_custom_bounded_working_window(self) -> None:
        broker = _BoundedWorkingBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "bounded-entry", max_wait=5, limit_price=1.25,
                side="buy", symbol="SPY260821C00780000", qty=1,
                position_intent="buy_to_open", attempt_id="bounded-intent",
            )

        self.assertIsNone(result)
        self.assertEqual(6, broker.get_calls)
        self.assertTrue(any(
            call.kwargs.get("event_type") == "entry_expired_no_fill"
            for call in record_flow.call_args_list
        ))

    def test_entry_uses_alpaca_quote_and_respects_price_ceiling(self) -> None:
        broker = _ExecutionQuoteBroker()
        with patch("broker.alpaca_orders._record_flow"), patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker.place_option_order(
                symbol="SPY260821C00780000", qty=2, side="buy",
                order_type="limit", limit_price=1.10, step_to_price=1.15,
                max_acceptable_price=1.28, position_intent="buy_to_open",
                order_context={"intent_id": "intent-123", "candidate_id": "candidate-456"},
            )

        self.assertEqual("filled", result["status"])
        self.assertEqual("1.25", broker.posted[0]["limit_price"])
        self.assertEqual(1.28, broker.wait_kwargs["step_to_price"])
        self.assertFalse(broker.wait_kwargs["allow_market_fallback"])
        self.assertEqual("celo-intent-123", broker.posted[0]["client_order_id"])
        self.assertEqual("intent-123", result["order_intent_id"])
        self.assertTrue(result["execution_attempt_id"])

    def test_entry_can_keep_authoritative_tradier_quote(self) -> None:
        broker = _ExecutionQuoteBroker()
        with patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker.place_option_order(
                symbol="SPY260821C00780000", qty=2, side="buy",
                order_type="limit", limit_price=1.10, step_to_price=1.15,
                max_acceptable_price=1.20, position_intent="buy_to_open",
                price_authority="tradier",
                order_context={
                    "intent_id": "intent-tradier",
                    "quote_bid": 1.05,
                    "quote_ask": 1.15,
                    "quote_mid": 1.10,
                    "quote_latency_ms": 42.5,
                },
            )

        self.assertEqual("filled", result["status"])
        self.assertEqual(0, broker.quote_calls)
        self.assertEqual("1.1", broker.posted[0]["limit_price"])
        self.assertEqual(1.15, broker.wait_kwargs["step_to_price"])
        events = [call.kwargs.get("event_type") for call in record_flow.call_args_list]
        self.assertIn("authoritative_quote", events)
        self.assertIn("execution_summary", events)

    def test_price_step_follows_alpaca_replacement_order_id(self) -> None:
        broker = _ReplacementFillBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "original-order", limit_price=1.35, step_to_price=1.30,
                side="sell", symbol="SPY260821P00780000", qty=2,
                position_intent="sell_to_close", attempt_id="attempt-replace",
            )

        self.assertEqual("filled", result["status"])
        self.assertEqual(1.31, result["confirmed_fill_price"])
        self.assertTrue(any(url.endswith("replacement-order") for url in broker.get_urls))
        self.assertEqual([], broker.cancelled)
        self.assertTrue(any(
            call.kwargs.get("event_type") == "price_step"
            and call.kwargs.get("order_id") == "replacement-order"
            and call.kwargs.get("parent_order_id") == "original-order"
            for call in record_flow.call_args_list
        ))

    def test_paper_market_fallback_preserves_close_intent(self) -> None:
        broker = _PaperFallbackBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow"), patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "limit-order", limit_price=1.30, side="sell",
                symbol="TSLA260821P00340000", qty=2,
                allow_market_fallback=True,
                position_intent="sell_to_close", attempt_id="attempt-1",
            )

        self.assertEqual("filled", result["status"])
        self.assertEqual("sell_to_close", broker.posted[0]["position_intent"])
        self.assertEqual("market", broker.posted[0]["type"])

    def test_routine_exit_does_not_leak_to_market(self) -> None:
        broker = _PaperFallbackBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "limit-exit", limit_price=1.30, side="sell",
                symbol="SPY260821P00780000", qty=2,
                position_intent="sell_to_close", attempt_id="routine-exit",
            )

        self.assertIsNone(result)
        self.assertEqual([], broker.posted)
        self.assertTrue(any(
            call.kwargs.get("event_type") == "limit_expired_no_fill"
            for call in record_flow.call_args_list
        ))

    def test_paper_entry_does_not_chase_unfilled_limit_at_market(self) -> None:
        broker = _PaperFallbackBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "limit-entry", limit_price=1.30, side="buy",
                symbol="SPY260821C00780000", qty=2,
                position_intent="buy_to_open", attempt_id="attempt-entry",
            )

        self.assertIsNone(result)
        self.assertEqual([], broker.posted)
        self.assertTrue(any(
            call.kwargs.get("event_type") == "entry_expired_no_fill"
            for call in record_flow.call_args_list
        ))

    def test_paper_fallback_is_blocked_until_cancel_is_broker_confirmed(self) -> None:
        broker = _UnconfirmedCancelBroker()
        with patch("config.get_settings", return_value={"paper_trading": True}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "limit-order", limit_price=1.30, side="buy",
                symbol="TSLA260821C00340000", qty=2,
                position_intent="buy_to_open", attempt_id="attempt-2",
            )

        self.assertIsNone(result)
        self.assertEqual([], broker.posted)
        self.assertTrue(any(
            call.kwargs.get("event_type") == "fallback_blocked_cancel_unconfirmed"
            and call.kwargs.get("is_issue") is True
            for call in record_flow.call_args_list
        ))

    def test_live_timeout_does_not_claim_cancel_without_broker_confirmation(self) -> None:
        broker = _LiveUnconfirmedCancelBroker()
        with patch("config.get_settings", return_value={"paper_trading": False}), patch(
            "broker.alpaca_orders.time.sleep"
        ), patch("broker.alpaca_orders._record_flow") as record_flow, patch(
            "broker.alpaca_orders.log_event"
        ):
            result = broker._wait_for_fill(
                "live-limit", limit_price=1.30, side="buy",
                symbol="SPY260821C00780000", qty=1,
                position_intent="buy_to_open", attempt_id="attempt-live",
            )

        self.assertIsNone(result)
        event_types = [call.kwargs.get("event_type") for call in record_flow.call_args_list]
        self.assertIn("cancel_unconfirmed", event_types)
        self.assertNotIn("terminal_no_fill", event_types)


class BrokerPositionAlignmentTests(unittest.TestCase):
    def test_flags_old_journal_open_trade_when_broker_is_flat(self) -> None:
        now = datetime.now().astimezone()
        issues = _find_db_only_positions(
            [{"id": 186, "ticker": "SPY", "contract_symbol": "SPY260821C00780000",
              "entry_time": (now - timedelta(minutes=10)).isoformat()}],
            [], [], now=now,
        )
        self.assertEqual(1, len(issues))
        self.assertEqual("journal_open_broker_flat", issues[0]["kind"])

    def test_does_not_flag_when_position_or_working_order_exists(self) -> None:
        now = datetime.now().astimezone()
        trade = {"id": 7, "contract_symbol": "TSLA260821P00340000",
                 "entry_time": (now - timedelta(minutes=10)).isoformat()}
        self.assertEqual([], _find_db_only_positions(
            [trade], [{"symbol": trade["contract_symbol"]}], [], now=now,
        ))
        self.assertEqual([], _find_db_only_positions(
            [trade], [], [{"symbol": trade["contract_symbol"]}], now=now,
        ))

    def test_allows_short_broker_visibility_grace_period(self) -> None:
        now = datetime.now().astimezone()
        trade = {"id": 8, "contract_symbol": "SPY260821P00780000",
                 "entry_time": (now - timedelta(seconds=30)).isoformat()}
        self.assertEqual([], _find_db_only_positions([trade], [], [], now=now))


class BrokerOrderLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trades_paper.db"
        _init_db_at(self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_flow_groups_events_and_links_fill_to_trade(self) -> None:
        settings = {
            "paper_trading": True,
            "active_broker_account_id": "alpaca:paper:acct-1",
        }
        with patch("config.get_settings", return_value=settings), patch(
            "database.broker_order_flow.get_conn", return_value=self.conn
        ):
            record_broker_order_event(
                attempt_id="attempt-1", event_type="submit_attempt",
                order_id="order-1", ticker="SPY", strategy_id="SPY_TREND_CONT",
                requested_qty=1,
            )
            record_broker_order_event(
                attempt_id="attempt-1", event_type="filled", status="filled",
                order_id="order-1", ticker="SPY", strategy_id="SPY_TREND_CONT",
                requested_qty=1, filled_qty=1, fill_price=2.15,
            )
            link_broker_order_to_trade("order-1", 42, link_kind="entry")

        with patch(
            "database.broker_order_flow._conn_for_mode", return_value=self.conn
        ):
            result = get_broker_order_flow(
                mode="paper", broker_account_id="alpaca:paper:acct-1"
            )

        self.assertEqual(1, result["summary"]["attempts"])
        self.assertEqual(1, result["summary"]["filled"])
        self.assertEqual(0, result["summary"]["unlinked_fills"])
        self.assertEqual(42, result["attempts"][0]["linked_trade_id"])
        self.assertEqual("linked_to_trade", result["attempts"][0]["final_event"])

    def test_account_filter_does_not_mix_broker_accounts(self) -> None:
        with patch(
            "database.broker_order_flow.get_conn", return_value=self.conn
        ):
            with patch("config.get_settings", return_value={
                "paper_trading": True,
                "active_broker_account_id": "alpaca:paper:acct-1",
            }):
                record_broker_order_event(
                    attempt_id="one", event_type="filled", filled_qty=1,
                    order_id="order-1",
                )
            with patch("config.get_settings", return_value={
                "paper_trading": True,
                "active_broker_account_id": "alpaca:paper:acct-2",
            }):
                record_broker_order_event(
                    attempt_id="two", event_type="filled", filled_qty=1,
                    order_id="order-2",
                )

        with patch(
            "database.broker_order_flow._conn_for_mode", return_value=self.conn
        ):
            result = get_broker_order_flow(
                mode="paper", broker_account_id="alpaca:paper:acct-1"
            )

        self.assertEqual(["one"], [row["attempt_id"] for row in result["attempts"]])


if __name__ == "__main__":
    unittest.main()
