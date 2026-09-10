from datetime import datetime, timedelta, time
import unittest
from unittest.mock import patch

from research.engine.models import Bar
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.gap_fill_rth import GapFillRTH
from strategy_health import gap_fill_exit, momentum_exit
from tests.test_momentum_exit_measurement import frame


def seed(entry=datetime(2026, 9, 10, 10, 5)):
    strategy = GapFillRTH()
    strategy._history = [Bar(entry-timedelta(minutes=5*(15-i)), 100, 101.25, 98.75, 100) for i in range(15)]
    return gap_fill_exit.entry_state(strategy)


class GapFillExitMeasurementTests(unittest.TestCase):
    def detect(self, bars, **changes):
        args = dict(entry_at="2026-09-10T10:05", entry_quote_at="2026-09-10T10:05:01",
                    seed=seed(), stop=95, target=1000, direction="bullish", now="2026-09-10T10:21")
        args.update(changes)
        return gap_fill_exit.first_exit(frame(bars), **args)

    def test_short_bug_baseline_and_low_water_correction_stay_separate(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 110, 60, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 100, 80, 81),
                Bar(datetime(2026, 9, 10, 10, 15), 81, 95, 80, 90)]
        kwargs = dict(stop=105, target=10, direction="bearish")
        self.assertIsNone(self.detect(bars, **kwargs))
        self.assertIsNone(self.detect(bars, **kwargs, short_low_water=True, now="2026-09-10T10:15"))
        self.assertEqual((datetime(2026, 9, 10, 10, 16), "atr_trailing_stop"),
                         self.detect(bars, **kwargs, short_low_water=True))

    def test_long_trail_does_not_change_and_never_uses_same_bar_future_low(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 140, 90, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 120, 100, 119),
                Bar(datetime(2026, 9, 10, 10, 15), 119, 120, 105, 110)]
        self.assertIsNone(self.detect(bars, now="2026-09-10T10:15"))
        self.assertEqual((datetime(2026, 9, 10, 10, 16), "atr_trailing_stop"), self.detect(bars))
        self.assertEqual(self.detect(bars), self.detect(bars, short_low_water=True))

    def test_gap_and_momentum_indicator_states_cannot_mix(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 99, 100)]
        self.assertNotEqual(gap_fill_exit.engine_hash(), momentum_exit.engine_hash())
        self.assertEqual("missing_indicator_state", self.detect(bars, seed={**seed(), 'engine_hash': momentum_exit.engine_hash()})[1])
        self.assertEqual("missing_indicator_state", self.detect(bars, seed=None)[1])
        self.assertIsNone(momentum_exit.restored(seed(), datetime(2026, 9, 10, 10, 5)))
        self.assertEqual("missing_indicator_state", self.detect(bars, seed={**seed(), 'trail_multiple': 3})[1])

    def test_gap_target_is_placeholder_and_session_decision_waits_for_close(self):
        bars = [Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 99, 100),
                Bar(datetime(2026, 9, 10, 10, 10), 100, 111, 99, 110)]
        self.assertIsNone(self.detect(bars, target=105, now="2026-09-10T10:15"))
        entry = datetime(2026, 9, 10, 10, 5)
        bars = [Bar(entry+timedelta(minutes=5*i), 100, 101.25, 98.75, 100) for i in range(71)]
        self.assertIsNone(self.detect(bars, now="2026-09-10T15:59:59"))
        self.assertEqual((datetime(2026, 9, 10, 16), 'session_flatten'), self.detect(bars, now="2026-09-10T16:00"))

    def test_reference_gap_signals_exit_bar_and_runtime_state_match_both_directions(self):
        for direction in (1, -1):
            before, day = datetime(2026, 9, 9, 14, 45), datetime(2026, 9, 10, 9, 30)
            bars = [Bar(before+timedelta(minutes=5*i), 100, 100.4, 99.6, 100) for i in range(15)]
            opened = 100+direction
            bars.append(Bar(day, opened, opened+.2, opened-.2, opened))
            bars.append(Bar(day+timedelta(minutes=5), opened, 101.25, 98.75, 100+direction*.25))
            for i in range(2, 78):
                price = 100+direction*(.25+(i-1)*.3 if i < 20 else 6-(i-20)*.8)
                prior = bars[-1].close
                bars.append(Bar(day+timedelta(minutes=5*i), prior, max(prior, price)+.15, min(prior, price)-.15, price))
            engine, saved, history = GapFillRTH(), None, []
            for bar in bars:
                history.append(bar)
                signal = engine.evaluate(history)
                if signal:
                    saved = (signal, gap_fill_exit.entry_state(engine))
                    break
            self.assertIsNotNone(saved)
            signal, snapshot = saved
            self.assertEqual(day+timedelta(minutes=5), signal.timestamp)
            trades = Simulator(SimulationConfig(session_exit_time=time(15, 55))).run(bars, GapFillRTH())
            self.assertEqual(1, len(trades))
            trade = trades[0]
            self.assertEqual('stop', trade.exit_reason)
            result = gap_fill_exit.first_exit(frame(bars), entry_at=trade.entry_time,
                entry_quote_at=trade.entry_time+timedelta(seconds=1), seed=snapshot, stop=signal.stop,
                target=signal.target, direction='bullish' if direction == 1 else 'bearish', now=day.replace(hour=16))
            self.assertEqual((trade.exit_time+timedelta(minutes=1), 'atr_trailing_stop'), result)
            with patch('trading.tested_strategy_research._emitted', set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates = evaluate_tested_research(frame(history), 'META', [gap_fill_exit.STRATEGY_ID], scope='gap-parity', now=trade.entry_time)
            self.assertEqual(1, len(candidates))
            self.assertEqual(gap_fill_exit.PROTOCOL, candidates[0].meta['authored_exit_protocol'])
            self.assertEqual(snapshot, candidates[0].meta['authored_exit_state'])
