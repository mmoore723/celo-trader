"""Production bridge tests for the reviewed TSLA two-leg pullback rule."""
from datetime import datetime
import unittest

import pandas as pd
import pytz

from trading.two_leg_trend_pullback_execution import STRATEGY_ID, update_two_leg_trend_pullback


ET = pytz.timezone("America/New_York")


def _bars() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for stamp in pd.date_range("2026-08-12 09:30", "2026-08-12 09:59", freq="min", tz="America/New_York"):
        rows.append({"time": stamp, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000, "rvol": 1.4})
    rows.extend([
        {"time": pd.Timestamp("2026-08-12 10:00", tz="America/New_York"), "open": 100.0, "high": 102.3, "low": 99.9, "close": 102.2, "volume": 1200, "rvol": 1.8},
        {"time": pd.Timestamp("2026-08-12 10:01", tz="America/New_York"), "open": 100.7, "high": 100.8, "low": 100.4, "close": 100.7, "volume": 1100, "rvol": 1.3},
        {"time": pd.Timestamp("2026-08-12 10:02", tz="America/New_York"), "open": 100.7, "high": 101.2, "low": 100.6, "close": 101.1, "volume": 1300, "rvol": 1.6},
    ])
    return pd.DataFrame(rows)


def _bearish_bars() -> pd.DataFrame:
    rows = _bars()
    rows.loc[rows["time"].dt.time == datetime(2026, 8, 12, 10, 0).time(),
             ["open", "high", "low", "close"]] = [100.0, 100.1, 97.7, 97.8]
    rows.loc[rows["time"].dt.time == datetime(2026, 8, 12, 10, 1).time(),
             ["open", "high", "low", "close"]] = [99.3, 99.6, 99.2, 99.3]
    rows.loc[rows["time"].dt.time == datetime(2026, 8, 12, 10, 2).time(),
             ["open", "high", "low", "close"]] = [99.3, 99.4, 98.8, 98.9]
    return rows


class TwoLegExecutionTests(unittest.TestCase):
    def test_finished_one_minute_reclaim_emits_once_with_manual_levels(self) -> None:
        state: dict[str, object] = {}
        signal, status = update_two_leg_trend_pullback(
            state, _bars(), ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 3)),
        )

        self.assertEqual("completed_1m_reclaim", status)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(STRATEGY_ID, signal.strategy_id)
        self.assertEqual("bullish", signal.direction)
        self.assertEqual(pd.Timestamp("2026-08-12 10:02", tz="America/New_York"), signal.trigger_bar)
        self.assertIn("reference_945", signal.meta)
        self.assertIn("pullback_low", signal.meta)
        self.assertIn("reclaim_level", signal.meta)
        self.assertIn("v2_stop", signal.meta)
        self.assertIn("v2_target", signal.meta)
        self.assertTrue(signal.meta["directional_confirmation"])
        self.assertTrue(signal.meta["pa_momentum_long"])

        duplicate, duplicate_status = update_two_leg_trend_pullback(
            state, _bars(), ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 3)),
        )
        self.assertIsNone(duplicate)
        self.assertEqual("already_emitted", duplicate_status)

    def test_currently_forming_reclaim_cannot_trigger(self) -> None:
        signal, status = update_two_leg_trend_pullback(
            {}, _bars(), ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 2)),
        )
        self.assertIsNone(signal)
        self.assertEqual("waiting_for_impulse_pullback_reclaim", status)

    def test_bearish_reclaim_requires_and_records_directional_confirmation(self) -> None:
        signal, status = update_two_leg_trend_pullback(
            {}, _bearish_bars(), ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 3)),
        )

        self.assertEqual("completed_1m_reclaim", status)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("bearish", signal.direction)
        self.assertTrue(signal.meta["directional_confirmation"])
        self.assertTrue(signal.meta["pa_momentum_short"])

    def test_replay_does_not_reenter_after_an_earlier_same_day_signal(self) -> None:
        rows = _bars()
        rows.loc[len(rows)] = {
            "time": pd.Timestamp("2026-08-12 10:03", tz="America/New_York"),
            "open": 101.1, "high": 101.4, "low": 100.9, "close": 101.3, "volume": 900, "rvol": 1.0,
        }
        signal, status = update_two_leg_trend_pullback(
            {}, rows, ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 4)),
        )
        self.assertIsNone(signal)
        self.assertEqual("waiting_for_impulse_pullback_reclaim", status)

    def test_weak_reclaim_is_rejected_and_later_candle_cannot_rescue_it(self) -> None:
        rows = _bars()
        rows.loc[rows.index[-1], ["open", "high", "low", "close"]] = [100.85, 101.1, 100.6, 100.9]

        signal, status = update_two_leg_trend_pullback(
            {}, rows, ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 3)),
        )
        self.assertIsNone(signal)
        self.assertEqual("waiting_for_impulse_pullback_reclaim", status)

        rows.loc[len(rows)] = {
            "time": pd.Timestamp("2026-08-12 10:03", tz="America/New_York"),
            "open": 100.9, "high": 102.0, "low": 100.85, "close": 101.95,
            "volume": 1500, "rvol": 2.0,
        }
        rescued, rescued_status = update_two_leg_trend_pullback(
            {}, rows, ticker="TSLA", now=ET.localize(datetime(2026, 8, 12, 10, 4)),
        )
        self.assertIsNone(rescued)
        self.assertEqual("waiting_for_impulse_pullback_reclaim", rescued_status)
