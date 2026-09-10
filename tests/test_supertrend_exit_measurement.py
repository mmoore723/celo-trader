from datetime import datetime, timedelta
import math
import unittest
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar
from research.engine.strategies.supertrend_reversal import SuperTrendReversal
from research.engine.supertrend_simulator import SuperTrendReversalSimulator
from strategy_health.supertrend_exit import first_exit, entry_state, engine_hash


def seed(trend=1, bar_time="2026-09-10T10:00"):
    return dict(engine_hash=engine_hash(), bar_time=bar_time, atr=1., close=100.,
                up=98., down=102., trend=trend, period=10, multiplier=3., rma=True)


def minute_frame(bars):
    return pd.DataFrame([dict(time=b.timestamp+timedelta(minutes=i), open=b.open,
                             high=b.high, low=b.low, close=b.close, volume=100)
                         for b in bars for i in range(5)])


class SupertrendExitMeasurementTests(unittest.TestCase):
    def detect(self, frame=None, **changes):
        if frame is None:
            frame = minute_frame([Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 94, 95)])
        args = dict(entry_at="2026-09-10T10:05", entry_quote_at="2026-09-10T10:05:01",
                    direction="bullish", seed=seed(), now="2026-09-10T10:10")
        args.update(changes)
        return first_exit(frame, **args)

    def test_opposite_flip_can_exit_at_the_end_of_entry_candle(self):
        self.assertEqual((datetime(2026, 9, 10, 10, 10), "opposite_flip"), self.detect())
        self.assertIsNone(self.detect(now="2026-09-10T10:09:59"))

    def test_short_exits_on_upward_flip(self):
        frame = minute_frame([Bar(datetime(2026, 9, 10, 10, 5), 100, 106, 99, 105)])
        self.assertEqual("opposite_flip", self.detect(frame, direction="bearish", seed=seed(-1))[1])

    def test_intrabar_stop_touch_does_not_exit_without_a_close_flip(self):
        frame = minute_frame([Bar(datetime(2026, 9, 10, 10, 5), 100, 106, 80, 100)])
        self.assertIsNone(self.detect(frame))

    def test_session_exit_uses_close_and_ignores_a_pending_1555_flip(self):
        frame = minute_frame([Bar(datetime(2026, 9, 10, 15, 50), 100, 101, 94, 95)])
        args = dict(entry_at="2026-09-10T15:50", entry_quote_at="2026-09-10T15:50:01",
                    seed=seed(bar_time="2026-09-10T15:45"))
        self.assertIsNone(self.detect(frame, **args, now="2026-09-10T15:55"))
        self.assertEqual((datetime(2026, 9, 10, 16), "session_flatten"),
                         self.detect(frame, **args, now="2026-09-10T16:00"))

    def test_seed_must_match_entry_time_side_and_engine(self):
        for change in [None, {}, {**seed(), "engine_hash": "outdated"}, {**seed(), "trend": -1},
                       {**seed(), "bar_time": "2026-09-10T09:55"}, {**seed(), "atr": float("nan")},
                       {**seed(), "rma": False}, {**seed(), "period": 20}]:
            self.assertEqual("missing_indicator_state", self.detect(seed=change)[1])
        self.assertEqual("entry_after_session_cutoff", self.detect(entry_at="2026-09-10T15:55")[1])
        self.assertEqual("late_entry_quote", self.detect(entry_quote_at="2026-09-10T10:10")[1])

    def test_missing_minutes_cannot_hide_an_earlier_flip(self):
        frame = minute_frame([Bar(datetime(2026, 9, 10, 10, 5), 100, 101, 94, 95)]).drop(index=1)
        self.assertIsNone(self.detect(frame))
        self.assertEqual("missing_bars", self.detect(frame, now="2026-09-10T10:16")[1])
        frame.loc[2, "close"] = float("nan")
        # Once all rows exist, malformed OHLC is also explicitly unmeasurable.
        frame.loc[1] = frame.loc[0]
        self.assertEqual("duplicate_bars", self.detect(frame)[1])

    def test_frozen_state_matches_reference_reversal_simulator_across_all_flips(self):
        start, bars = datetime(2026, 9, 10, 9, 30), []
        for i in range(78):
            price = 100 + 12*math.sin(i/4)
            prior = bars[-1].close if bars else price
            bars.append(Bar(start+timedelta(minutes=5*i), prior, max(prior, price)+.4,
                            min(prior, price)-.4, price))
        engine, states, history = SuperTrendReversal(), {}, []
        for bar in bars:
            history.append(bar)
            signal = engine.evaluate(history)
            if signal is not None:
                states[bar.timestamp] = entry_state(engine)
        trades = SuperTrendReversalSimulator().run(bars, SuperTrendReversal())
        self.assertGreater(len(trades), 3)
        self.assertTrue(any(t.exit_reason == "session" for t in trades))
        for trade in trades:
            actual = first_exit(minute_frame(bars), entry_at=trade.entry_time,
                                entry_quote_at=trade.entry_time+timedelta(seconds=1),
                                direction="bullish" if trade.side.value == "long" else "bearish",
                                seed=states[trade.signal_time], now=start.replace(hour=16, minute=0))
            expected = (trade.exit_time, "opposite_flip") if trade.exit_reason == "opposite_flip" else (
                trade.exit_time+timedelta(minutes=5), "session_flatten")
            self.assertEqual(expected, actual)

    def test_live_research_signal_saves_exact_entry_state_without_future_bars(self):
        from trading.tested_strategy_research import evaluate_tested_research
        from strategy_health.supertrend_exit import PROTOCOL, STRATEGY_ID
        start, bars, engine = datetime(2026, 9, 10, 9, 30), [], SuperTrendReversal()
        for i in range(50):
            price = 100 + 12*math.sin(i/4)
            prior = bars[-1].close if bars else price
            bars.append(Bar(start+timedelta(minutes=5*i), prior, max(prior, price)+.4,
                            min(prior, price)-.4, price))
            if engine.evaluate(bars) is not None:
                break
        frame = minute_frame(bars)
        now = bars[-1].timestamp+timedelta(minutes=5)
        with patch("trading.tested_strategy_research._emitted", set()):
            signals = evaluate_tested_research(frame, "META", [STRATEGY_ID], scope="test", now=now)
        self.assertEqual(1, len(signals))
        self.assertEqual(PROTOCOL, signals[0].meta["authored_exit_protocol"])
        self.assertEqual(entry_state(engine), signals[0].meta["authored_exit_state"])
        self.assertEqual(now, signals[0].trigger_bar.to_pydatetime())
        self.assertTrue(signals[0].meta["observation_only"])
