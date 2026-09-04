"""Offline missed-minute regression; no broker orders or historical profit claims."""
from datetime import datetime
from threading import Event
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from auth.context import get_current_user_id, set_current_user
from config.strategy_catalog import REVIEWED_STRATEGIES
from tests.test_two_leg_execution import _bars, ET
from trading.entry.injected_setups import evaluate_injected_setups, TWO_LEG
from trading.loop.research_worker import ResearchWorker
from trading.loop.scan_schedule import (
    execution_tickers, run_execution_batch, seconds_until_scan, record_scan_timing,
)


def settings():
    return {"paper_trading": True, "active_broker_account_id": "test-paper",
            **{r.setting_key: True for r in REVIEWED_STRATEGIES.values()}}


class ScanTimingTests(unittest.TestCase):
    def setUp(self):
        previous = get_current_user_id()
        set_current_user("timing-test", "timing-test", False)
        self.addCleanup(set_current_user, previous, previous, False)

    def test_only_enabled_tickers_are_in_order_lane(self):
        self.assertEqual(["SPY", "TSLA"], execution_tickers(
            ["AMZN", "SPY", "QQQ", "TSLA", "META"], settings()))

    def test_disabled_strategies_still_get_management_only_pass(self):
        tick = Mock()
        run_execution_batch(["QQQ"], {}, Event(), tick, "broker", "market")
        tick.assert_called_once_with("broker", "market", scan_ticker="", execution_only=True)

    def test_stop_prevents_later_ticker_execution(self):
        stop, tick = Event(), Mock()
        tick.side_effect = lambda *a, **kw: stop.set()
        run_execution_batch(["SPY", "TSLA"], settings(), stop, tick, None, None)
        self.assertEqual(1, tick.call_count)

    def test_boundary_wait_never_adds_a_full_minute(self):
        for second in (0, 9, 10, 21, 59):
            wait = seconds_until_scan(datetime(2026, 9, 4, 10, 24, second))
            self.assertGreaterEqual(wait, 1)
            self.assertLessEqual(wait, 10)

    def test_blocked_research_does_not_hide_a_one_minute_setup(self):
        entered, release, parent_stop = Event(), Event(), Event()
        worker = None
        try:
            def slow_research(*_args):
                entered.set()
                release.wait(5)
            with patch("trading.loop.research_worker.get_settings", return_value=settings()):
                worker = ResearchWorker("timing-test", parent_stop, slow_research, lambda: ())
                self.assertTrue(worker.submit({"settings": settings(), "tickers": ["META"]}))
                self.assertTrue(entered.wait(2))
                state, signals, calls = {}, [], []
                now = ET.localize(datetime(2026, 8, 12, 10, 2, 27))
                frame = _bars()
                def tick(_alpaca, _tradier, *, scan_ticker, execution_only):
                    calls.append((scan_ticker, execution_only))
                    if scan_ticker == "TSLA":
                        with patch("trading.entry.injected_setups._now_et", return_value=now):
                            found, _, _ = evaluate_injected_setups(
                                state, frame, "TSLA", {TWO_LEG}, set(), Mock(), settings())
                        signals.extend(found)
                run_execution_batch(["SPY", "TSLA", "META"], settings(), parent_stop, tick, None, None)
                self.assertEqual([], signals)  # Reclaim candle is still forming.
                now = ET.localize(datetime(2026, 8, 12, 10, 3, 1))
                run_execution_batch(["SPY", "TSLA", "META"], settings(), parent_stop, tick, None, None)
                self.assertEqual(1, len(signals))  # Research is STILL blocked.
                self.assertEqual("bullish", signals[0].direction)
                run_execution_batch(["SPY", "TSLA", "META"], settings(), parent_stop, tick, None, None)
                self.assertEqual(1, len(signals))  # No duplicate setup/order request.
                self.assertTrue(worker.busy)
                self.assertNotIn(("META", True), calls)
        finally:
            release.set()
            if worker:
                worker.close()

    def test_missed_and_stale_bars_are_reported(self):
        state = {}
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-09-04 10:23"])})
        with self.assertLogs("celo_trader.trading_logic", level="INFO") as logs:
            record_scan_timing(state, "TSLA", frame, datetime(2026, 9, 4, 10, 24))
            frame["time"] = pd.to_datetime(["2026-09-04 10:25"])
            record_scan_timing(state, "TSLA", frame, datetime(2026, 9, 4, 10, 26))
            record_scan_timing(state, "TSLA", frame, datetime(2026, 9, 4, 10, 27))
        self.assertTrue(any("skipped_bars=1" in line for line in logs.output))
        self.assertTrue(any("stale_seconds=60.0" in line for line in logs.output))

    def test_new_trading_day_does_not_count_overnight_minutes_as_missed(self):
        state = {"execution_scan_coverage": {"TSLA": "2026-09-03T15:54:00"}}
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-09-04 09:45"])})
        with self.assertLogs("celo_trader.trading_logic", level="INFO") as logs:
            record_scan_timing(state, "TSLA", frame, datetime(2026, 9, 4, 9, 46))
        self.assertIn("skipped_bars=0", logs.output[0])
