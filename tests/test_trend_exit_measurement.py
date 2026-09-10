from datetime import datetime, timedelta, time
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.trend_continuation import TrendContinuation
from strategy_health import trend_exit, impulse_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return trend_exit.entry_state(TrendContinuation())


class TrendExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args = dict(entry_at='2026-09-10T10:05', entry_quote_at='2026-09-10T10:05:01',
                    seed=seed(), stop=98, target=104, direction='bullish', now='2026-09-10T10:15')
        args.update(changes)
        return trend_exit.first_exit(candles() if data is None else data, **args)

    def test_skip_entry_wait_for_completed_bar_and_stop_wins_ambiguous_bar(self):
        data = candles()
        data.loc[0:4, 'low'] = 90
        self.assertIsNone(self.detect(data))
        data.loc[5, ['low', 'high']] = [97, 105]
        self.assertIsNone(self.detect(data, now='2026-09-10T10:14:59'))
        expected = (datetime(2026, 9, 10, 10, 15), 'underlying_stop')
        self.assertEqual(expected, self.detect(data))
        self.assertEqual(expected, self.detect(data, stop=104, target=98, direction='bearish'))

    def test_both_target_directions_and_first_event_are_preserved(self):
        data = candles()
        data.loc[5, 'high'] = 105
        self.assertEqual('underlying_2r_target', self.detect(data)[1])
        data.loc[5, ['high', 'low']] = [101, 97]
        self.assertEqual('underlying_2r_target', self.detect(data, stop=104, target=98, direction='bearish')[1])
        data.loc[10, 'high'] = 106
        self.assertEqual((datetime(2026, 9, 10, 10, 15), 'underlying_stop'),
                         self.detect(data, now='2026-09-10T10:25'))

    def test_default_impulse_cap_is_unchanged_but_trend_uses_75_bars(self):
        args = dict(entry_at='2026-09-10T10:05', entry_quote_at='2026-09-10T10:05:01',
                    stop=98, target=104, direction='bullish', now='2026-09-10T12:10')
        self.assertEqual('time_cap_120m', impulse_exit.first_exit(candles(), **args)[1])
        self.assertIsNone(self.detect(now='2026-09-10T12:10'))
        early = candles('2026-09-10T09:30', 390)
        args = dict(entry_at='2026-09-10T09:30', entry_quote_at='2026-09-10T09:30:01')
        self.assertIsNone(self.detect(early, **args, now='2026-09-10T15:49:59'))
        self.assertEqual((datetime(2026, 9, 10, 15, 50), 'time_cap_75bars'),
                         self.detect(early, **args, now='2026-09-10T15:50'))

    def test_session_close_is_not_the_open_of_the_last_bar(self):
        data = candles(minutes=355)
        self.assertIsNone(self.detect(data, now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026, 9, 10, 16), 'session_flatten'), self.detect(data, now='2026-09-10T16:00'))

    def test_bad_state_or_prices_never_become_measured_outcomes(self):
        for state in (None, {}, {**seed(), 'engine_hash': 'different'},
                      {**seed(), 'config': {**seed()['config'], 'reward_risk': 3}}):
            self.assertEqual('missing_exit_state', self.detect(seed=state)[1])
        for bad in ('not a number', None, float('nan')):
            self.assertEqual('invalid_levels', self.detect(stop=bad)[1])
        self.assertEqual('missing_bars', self.detect(candles().drop(index=6), now='2026-09-10T10:21')[1])
        self.assertEqual('invalid_bars', self.detect(candles().drop(columns=['high']))[1])
        self.assertEqual('late_entry_quote', self.detect(entry_quote_at='2026-09-10T10:10')[1])

    def test_every_reference_trade_matches_exit_reason_and_completed_bar_time(self):
        for direction in (1, -1):
            before, day = datetime(2026, 9, 9, 12, 40), datetime(2026, 9, 10, 9, 30)
            bars = [Bar(before+timedelta(minutes=5*i), 100, 100.2, 99.8, 100) for i in range(40)]
            for i in range(78):
                price = 100+direction*(i*.3 if i < 35 else 10.5-(i-35)*.4)
                prior = bars[-1].close
                bars.append(Bar(day+timedelta(minutes=5*i), prior, max(prior,price)+.05, min(prior,price)-.05, price))
            engine, history, signals = TrendContinuation(), [], {}
            for bar in bars:
                history.append(bar)
                signal = engine.evaluate(history)
                if signal:
                    signals[signal.timestamp] = signal
            trades = Simulator(SimulationConfig(session_exit_time=time(15, 55))).run(bars, TrendContinuation())
            self.assertGreater(len(trades), 3)
            reasons = {'stop': 'underlying_stop', 'target': 'underlying_2r_target',
                       'time': 'time_cap_75bars', 'session': 'session_flatten'}
            for trade in trades:
                signal = signals[trade.signal_time]
                result = trend_exit.first_exit(frame(bars), entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1), seed=seed(), stop=signal.stop,
                    target=signal.target, direction='bullish' if signal.side is Side.LONG else 'bearish', now=day.replace(hour=16))
                self.assertEqual((trade.exit_time+timedelta(minutes=5), reasons[trade.exit_reason]), result)
            first = next(iter(signals.values()))
            with patch('trading.tested_strategy_research._emitted', set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates = evaluate_tested_research(frame([b for b in bars if b.timestamp <= first.timestamp]),
                    'META', [trend_exit.STRATEGY_ID], scope='trend-parity', now=first.timestamp+timedelta(minutes=5))
            self.assertEqual(1, len(candidates))
            self.assertEqual(trend_exit.PROTOCOL, candidates[0].meta['authored_exit_protocol'])
            self.assertEqual(seed(), candidates[0].meta['authored_exit_state'])
            self.assertEqual(first.stop, candidates[0].meta['underlying_stop'])
            self.assertEqual(first.target, candidates[0].meta['underlying_target'])
