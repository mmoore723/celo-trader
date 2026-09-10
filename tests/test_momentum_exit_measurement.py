from datetime import datetime, timedelta, time
import unittest
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.opening_momentum_rth import OpeningMomentumRTH
from strategy_health.momentum_exit import entry_state, first_exit, PROTOCOL, STRATEGY_ID


def seed(entry=datetime(2026, 9, 10, 10, 5)):
    strategy = OpeningMomentumRTH()
    strategy._history = [Bar(entry-timedelta(minutes=5*(15-i)), 100, 101.25, 98.75, 100) for i in range(15)]
    return entry_state(strategy)


def frame(bars):
    return pd.DataFrame([dict(time=b.timestamp+timedelta(minutes=i), open=b.open, high=b.high,
                             low=b.low, close=b.close, volume=100) for b in bars for i in range(5)])


class MomentumExitMeasurementTests(unittest.TestCase):
    def detect(self, bars, **changes):
        args = dict(entry_at="2026-09-10T10:05", entry_quote_at="2026-09-10T10:05:01",
                    seed=seed(), stop=95, target=1000, direction="bullish", now="2026-09-10T10:21")
        args.update(changes)
        return first_exit(frame(bars) if not isinstance(bars, pd.DataFrame) else bars, **args)

    def test_trail_moves_only_after_close_and_never_retroactively(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 140, 90, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 120, 100, 119),
                Bar(datetime(2026, 9, 10, 10, 15), 119, 120, 105, 110)]
        self.assertIsNone(self.detect(bars, now="2026-09-10T10:15"))
        self.assertEqual((datetime(2026, 9, 10, 10, 16), "atr_trailing_stop"), self.detect(bars))

    def test_short_trail_uses_low_water_mark(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 110, 60, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 100, 80, 81),
                Bar(datetime(2026, 9, 10, 10, 15), 81, 95, 80, 90)]
        self.assertIsNone(self.detect(bars, stop=105, target=10, direction="bearish", now="2026-09-10T10:15"))
        # Characterize the original bug; do not rewrite the original evidence.
        self.assertIsNone(self.detect(bars, stop=105, target=10, direction="bearish"))
        self.assertIsNone(self.detect(bars, stop=105, target=10, direction="bearish",
                                     short_low_water=True, now="2026-09-10T10:15"))
        self.assertEqual((datetime(2026, 9, 10, 10, 16), "atr_trailing_stop"), self.detect(
            bars, stop=105, target=10, direction="bearish", short_low_water=True))

    def test_stop_touch_uses_first_completed_minute_not_whole_five_minute_close(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 99, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 101, 99, 100)]
        data = frame(bars)
        data.loc[7, "low"] = 94
        self.assertIsNone(self.detect(data, now="2026-09-10T10:12:59"))
        self.assertEqual((datetime(2026, 9, 10, 10, 13), "atr_trailing_stop"), self.detect(data))

    def test_missing_seed_or_minute_is_not_a_win_or_an_invented_stop(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 99, 100)]
        self.assertEqual("missing_indicator_state", self.detect(bars, seed=None)[1])
        self.assertEqual("missing_indicator_state", self.detect(bars, seed={**seed(), "engine_hash": "changed"})[1])
        self.assertEqual("missing_bars", self.detect(frame(bars).drop(index=2))[1])
        self.assertEqual("late_entry_quote", self.detect(bars, entry_quote_at="2026-09-10T10:10")[1])
        self.assertEqual("invalid_levels", self.detect(bars, stop=float("nan"))[1])

    def test_placeholder_target_is_never_a_profit_exit(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 99, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 111, 99, 110)]
        self.assertIsNone(self.detect(bars, target=105, now="2026-09-10T10:15"))

    def test_session_and_time_caps_are_completed_bar_decisions(self):
        entry = datetime(2026, 9, 10, 10, 5)
        bars = [Bar(entry+timedelta(minutes=5*i), 100, 101.25, 98.75, 100) for i in range(71)]
        self.assertEqual((datetime(2026, 9, 10, 16), "session_flatten"), self.detect(bars, now="2026-09-10T16:00"))
        early = entry.replace(hour=9, minute=30)
        bars = [Bar(early+timedelta(minutes=5*i), 100, 101.25, 98.75, 100) for i in range(76)]
        self.assertEqual((datetime(2026, 9, 10, 15, 50), "time_cap_75bars"), self.detect(
            bars, entry_at=early, entry_quote_at=early+timedelta(seconds=1), seed=seed(early), now="2026-09-10T16:00"))

    def test_reference_simulator_stop_bar_matches_one_minute_observation_for_both_sides(self):
        for direction in (1, -1):
            before = datetime(2026, 9, 9, 14, 45)
            bars = [Bar(before+timedelta(minutes=5*i), 100, 100.4, 99.6, 100) for i in range(15)]
            day = datetime(2026, 9, 10, 9, 30)
            for i in range(78):
                price = 100 + direction*(i*.25 if i < 20 else 5-(i-20)*.6)
                prior = bars[-1].close
                bars.append(Bar(day+timedelta(minutes=5*i), prior, max(prior, price)+.15,
                                min(prior, price)-.15, price))
            engine, saved, history = OpeningMomentumRTH(), None, []
            for b in bars:
                history.append(b)
                signal = engine.evaluate(history)
                if signal:
                    saved = (signal, entry_state(engine))
                    break
            self.assertIsNotNone(saved)
            signal, snapshot = saved
            trades = Simulator(SimulationConfig(session_exit_time=time(15, 55))).run(bars, OpeningMomentumRTH())
            self.assertEqual(1, len(trades))
            trade = trades[0]
            self.assertEqual("stop", trade.exit_reason)
            result = first_exit(frame(bars), entry_at=trade.entry_time,
                entry_quote_at=trade.entry_time+timedelta(seconds=1), seed=snapshot,
                stop=signal.stop, target=signal.target, direction="bullish" if direction == 1 else "bearish",
                now=day.replace(hour=16, minute=0))
            self.assertEqual((trade.exit_time+timedelta(minutes=1), "atr_trailing_stop"), result)
            if direction == 1:
                self.assertEqual(result, first_exit(frame(bars), entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1), seed=snapshot,
                    stop=signal.stop, target=signal.target, direction="bullish",
                    now=day.replace(hour=16, minute=0), short_low_water=True))
            with patch("trading.tested_strategy_research._emitted", set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates = evaluate_tested_research(frame(history), "META", [STRATEGY_ID], scope="test", now=trade.entry_time)
            self.assertEqual(1, len(candidates))
            self.assertEqual(PROTOCOL, candidates[0].meta["authored_exit_protocol"])
            self.assertEqual(snapshot, candidates[0].meta["authored_exit_state"])
