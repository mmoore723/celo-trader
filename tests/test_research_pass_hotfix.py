from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from strategies.base import Signal
from trading.loop.research_pass import market_readers, observe_ticker, run_research_pass
from trading.diagnostics.strategy_scan import scan_message, log_strategy_scan
from tests.test_scan_timing_hotfix import settings


class ResearchPassTests(unittest.TestCase):
    def setUp(self):
        self.exits = patch("trading.loop.research_pass.capture_authored_exits").start()
        self.profit = patch("trading.loop.research_pass.capture_profit_protection").start()
        self.addCleanup(patch.stopall)

    def test_pending_exit_sweep_runs_after_close_without_new_signal_scans(self):
        market = Mock()
        market.is_market_open.return_value = False
        with patch("trading.loop.research_pass.observe_ticker") as observer:
            run_research_pass((market, Mock()), {"settings": {}, "tickers": ["META"]}, {}, lambda: False)
        self.exits.assert_called_once()
        self.profit.assert_called_once()
        observer.assert_not_called()

    def test_market_readers_have_no_order_or_account_mutation_capability(self):
        readers = market_readers(Mock(), Mock())
        for reader in readers:
            for forbidden in ("place_option_order", "cancel_order", "_post", "_delete", "get_account"):
                self.assertFalse(hasattr(reader, forbidden))

    def test_profit_quotes_checkpoint_between_tickers_without_skipping_scans(self):
        with patch('trading.loop.research_pass.monotonic', side_effect=[0, 10, 35, 40]), patch(
            'trading.loop.research_pass.observe_ticker',
        ) as observe, patch('trading.loop.research_pass.maybe_observe'):
            run_research_pass((Mock(), Mock()), dict(settings={},tickers=['SPY','META'],risk=Mock(),balance=4000), {}, lambda:False)
        self.assertEqual(2,self.profit.call_count)
        self.assertEqual(['SPY','META'],[call.args[2] for call in observe.call_args_list])

    def test_all_watchlist_names_archive_when_entry_strategies_are_disabled(self):
        market = Mock()
        market.is_market_open.return_value = True
        market.get_session_bars.return_value = ([{
            "t": "2026-09-04T14:24:00Z", "o": 100, "h": 101,
            "l": 99, "c": 100.5, "v": 1000,
        }], False, True)
        names = ["SPY", "TSLA", "QQQ", "AMZN", "NVDA", "AAPL", "AMD", "META", "NFLX"]
        with patch("trading.loop.research_pass.record_scanner_candles") as archive, patch(
            "trading.loop.research_pass.maybe_observe",
        ):
            run_research_pass((market, Mock()), {
                "settings": {"shadow_ledger_enabled": False}, "tickers": names,
                "balance": 4000, "risk": Mock(),
            }, {}, lambda: False)
        self.assertEqual(names, [c.args[0] for c in archive.call_args_list])

    def test_quote_failure_does_not_erase_archived_candles_or_stop_other_names(self):
        with patch("trading.loop.research_pass.observe_ticker", side_effect=[RuntimeError("timeout"), None]) as observer, patch(
            "trading.loop.research_pass.maybe_observe",
        ):
            run_research_pass((Mock(), Mock()), {
                "settings": {}, "tickers": ["SPY", "TSLA"], "balance": 4000, "risk": Mock(),
            }, {}, lambda: False)
        self.assertEqual(2, observer.call_count)

    def test_only_research_ids_go_to_observation_router(self):
        market = Mock()
        market.get_session_bars.return_value = ([{
            "t": "2026-09-04T14:24:00Z", "o": 100, "h": 101,
            "l": 99, "c": 100.5, "v": 1000,
        }], False, True)
        market.get_bars.return_value = ([], False)
        with ExitStack() as stack:
            for name in ("record_scanner_candles", "capture_due_candidate_option_quotes"):
                stack.enter_context(patch(f"trading.loop.research_pass.{name}"))
            stack.enter_context(patch(
                "trading.loop.research_pass.load_scanner_candles", return_value=pd.DataFrame(),
            ))
            stack.enter_context(patch("trading.loop.research_pass.evaluate_injected_setups", return_value=([], {}, None)))
            route = stack.enter_context(patch("trading.loop.research_pass.route_signals", return_value=[]))
            observe_ticker(market, Mock(), "TSLA", settings(), {}, Mock(), 4000, lambda: False)
        args = route.call_args.kwargs
        self.assertEqual(set(), args["enabled_strategies"])
        self.assertIn("V2_TSLA_TWO_LEG_TREND_PULLBACK", args["observation_only_strategies"])
        self.assertIn("V2_SPY_TREND_CONT", args["observation_only_strategies"])
        self.assertTrue(args["observation_scope"].startswith("research_worker:"))

    def test_tested_library_signal_on_non_native_ticker_reaches_option_observer(self):
        market = Mock()
        market.get_session_bars.return_value = ([{
            "t": "2026-09-04T14:24:00Z", "o": 100, "h": 101,
            "l": 99, "c": 100.5, "v": 1000,
        }], False, True)
        market.get_bars.return_value = ([{
            't':'2026-09-03T14:20:00Z','o':100,'h':101,'l':99,'c':100.5,'v':1000,
        }], False)
        signal = Signal(
            strategy_id="V2_TREND_CONT", direction="bullish", confidence=0.7,
            rvol=0.0, trigger_bar=pd.Timestamp("2026-09-04T10:25:00"),
            meta={"observation_only": True},
        )
        research_settings = {
            **settings(), "shadow_ledger_enabled": True,
            "research_strategy_ids": ["V2_TREND_CONT"],
        }
        with ExitStack() as stack:
            for name in ("record_scanner_candles", "capture_due_candidate_option_quotes"):
                stack.enter_context(patch(f"trading.loop.research_pass.{name}"))
            stack.enter_context(patch(
                "trading.loop.research_pass.load_scanner_candles", return_value=pd.DataFrame(),
            ))
            stack.enter_context(patch("trading.loop.research_pass.evaluate_injected_setups", return_value=([], {}, None)))
            stack.enter_context(patch("trading.loop.research_pass.route_signals", return_value=[]))
            tested = stack.enter_context(patch("trading.loop.research_pass.evaluate_tested_research", return_value=[signal]))
            screen = stack.enter_context(patch("scanner.premarket_eligibility.screen_signal", return_value=False))
            observe = stack.enter_context(patch("trading.loop.research_pass.observe_candidate_contract"))
            marked = stack.enter_context(patch("trading.loop.research_pass.mark_candidate_observed_only"))
            observe_ticker(market, Mock(), "AAPL", research_settings, {}, Mock(), 4000, lambda: False)
        observe.assert_called_once()
        self.assertEqual("AAPL", observe.call_args.kwargs["ticker"])
        self.assertIs(signal, observe.call_args.kwargs["signal"])
        self.assertTrue(observe.call_args.kwargs["research_only"])
        self.assertEqual(1,len(tested.call_args.kwargs['history_5m']))
        market.get_bars.assert_called_once_with('AAPL','5Min',limit=1500)
        screen.assert_called_once()
        self.assertEqual(screen.call_args.args[:3], (market, "AAPL", signal))
        marked.assert_called_once_with(signal)

    def test_authorized_ticker_research_uses_separate_dedupe_scope(self):
        from importlib import import_module
        route = import_module("strategy_router.route")
        evaluator = Mock(return_value=None)
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        with patch.object(route, "ACTIVE_STRATEGIES", [("V2_SPY_TREND_CONT", evaluator)]), patch.object(
            route, "_authorized_for_order", return_value=True,
        ), patch.object(route, "compute_adx", return_value=30):
            result = route.route_signals(
                frame, "SPY", enabled_strategies=set(), quiet=True, prepared_today=frame,
                observation_only_strategies={"V2_SPY_TREND_CONT"}, observation_scope="research:user:a",
            )
        self.assertEqual([], result)
        self.assertEqual("research:user:a", evaluator.call_args.kwargs["execution_scope"])

    def test_misleading_execution_messages_are_not_used_for_research(self):
        signal = SimpleNamespace(strategy_id="V2_ORB_PULLBACK")
        self.assertIn("Research only", scan_message("AMZN", set(), {}, [signal]))
        message = scan_message("TSLA", {signal.strategy_id},
                               {signal.strategy_id: "outside_validated_direction"}, [])
        self.assertIn("calls only", message)
        self.assertNotIn("evaluating PUT", message)
        self.assertNotIn("ALL 3", message)

    def test_actual_signal_is_not_described_as_a_fill(self):
        signal = SimpleNamespace(strategy_id="V2_ORB_PULLBACK")
        message = scan_message("TSLA", {signal.strategy_id}, {}, [signal])
        self.assertIn("Setup found", message)
        self.assertIn("no fill confirmed", message)

    def test_shared_expiry_status_names_the_actual_strategy(self):
        strategy = "V2_TSLA_TWO_LEG_TREND_PULLBACK"
        message = scan_message("TSLA", {strategy}, {strategy: "entry_window_expired"}, [])
        self.assertIn("Two-leg: its entry time has passed", message)
        self.assertNotIn("ORB:", message)

    def test_narration_is_once_per_minute_unless_result_changes(self):
        state = {}
        now = datetime(2026, 9, 4, 10, 25)
        with patch("trading.diagnostics.strategy_scan.log_event") as log:
            for _ in range(6):
                log_strategy_scan(state, "TSLA", {"V2_ORB_PULLBACK"}, {}, [], now)
        self.assertEqual(1, log.call_count)
