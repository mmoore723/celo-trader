from datetime import datetime, timedelta, time
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.fair_value_gap import FairValueGap
from research.engine.strategies.trend_continuation import TrendContinuation
from strategy_health import fvg_exit, trend_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return fvg_exit.entry_state(FairValueGap())


def setup_bars(direction, outcome):
    day = datetime(2026, 9, 10, 9, 30)
    bars = []
    formation = {
        18:(101.8,101.85,101.75,101.8), 19:(101.8,102.5,101.8,102.4),
        20:(102.3,102.45,102.1,102.3), 21:(102.3,102.5,102.15,102.3),
        22:(102.3,102.5,102.15,102.4), 23:(102.4,102.5,101.95,102.25),
    }
    for i in range(78):
        price = 100+i*.1 if i < 18 else 102.25+outcome*max(0,i-24)*.4
        o,h,low,c = formation.get(i,(price,price+.05,price-.05,price))
        if direction < 0:
            o,h,low,c = 200-o,200-low,200-h,200-c
        bars.append(Bar(day+timedelta(minutes=5*i),o,h,low,c))
    return bars


class FvgExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args = dict(entry_at='2026-09-10T10:05', entry_quote_at='2026-09-10T10:05:01',
                    seed=seed(), stop=98, target=104, direction='bullish', now='2026-09-10T10:15')
        args.update(changes)
        return fvg_exit.first_exit(candles() if data is None else data, **args)

    def test_entry_candle_skipped_and_incomplete_bar_cannot_decide(self):
        data = candles()
        data.loc[0:4, 'low'] = 90
        self.assertIsNone(self.detect(data))
        data.loc[5, ['low', 'high']] = [97, 105]
        self.assertIsNone(self.detect(data, now='2026-09-10T10:14:59'))
        for direction, stop, target in [('bullish',98,104), ('bearish',104,98)]:
            self.assertEqual((datetime(2026,9,10,10,15),'underlying_stop'),
                self.detect(data, direction=direction, stop=stop, target=target))

    def test_targets_in_both_directions_and_no_later_replacement(self):
        data = candles()
        data.loc[5, 'high'] = 105
        data.loc[10, 'low'] = 90
        self.assertEqual((datetime(2026,9,10,10,15),'underlying_2r_target'),
                         self.detect(data, now='2026-09-10T10:25'))
        data.loc[5, ['high','low']] = [101,97]
        self.assertEqual('underlying_2r_target', self.detect(data, direction='bearish',stop=104,target=98)[1])

    def test_declared_hold_and_session_boundaries(self):
        self.assertIsNone(self.detect(now='2026-09-10T12:10'))
        early = candles('2026-09-10T09:30',390)
        args = dict(entry_at='2026-09-10T09:30',entry_quote_at='2026-09-10T09:30:01')
        self.assertIsNone(self.detect(early, **args, now='2026-09-10T15:49:59'))
        self.assertEqual('time_cap_75bars', self.detect(early, **args, now='2026-09-10T15:50')[1])
        self.assertIsNone(self.detect(candles(minutes=355),now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),
                         self.detect(candles(minutes=355),now='2026-09-10T16:00'))

    def test_missing_or_wrong_proof_and_bad_data_are_not_results(self):
        for state in [None,{},trend_exit.entry_state(TrendContinuation()),
                      {**seed(),'config':{**seed()['config'],'reward_risk':3}}]:
            self.assertEqual('missing_exit_state',self.detect(seed=state)[1])
        self.assertEqual('invalid_levels',self.detect(stop=None)[1])
        self.assertEqual('missing_bars',self.detect(candles().drop(index=6),now='2026-09-10T10:21')[1])
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:10')[1])

    def test_original_simulator_reference_and_runtime_metadata(self):
        seen = set()
        for direction in (1,-1):
            for outcome in (1,-1):
                bars = setup_bars(direction,outcome)
                engine, history, signals = FairValueGap(), [], {}
                for bar in bars:
                    history.append(bar)
                    signal = engine.evaluate(history)
                    if signal:
                        signals[signal.timestamp] = signal
                trades = Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,FairValueGap())
                self.assertGreater(len(trades),0)
                reasons = {'stop':'underlying_stop','target':'underlying_2r_target','session':'session_flatten','time':'time_cap_75bars'}
                for trade in trades:
                    signal = signals[trade.signal_time]
                    result = fvg_exit.first_exit(frame(bars),entry_at=trade.entry_time,
                        entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                        direction='bullish' if signal.side is Side.LONG else 'bearish',now=datetime(2026,9,10,16))
                    self.assertEqual((trade.exit_time+timedelta(minutes=5),reasons[trade.exit_reason]),result)
                    seen.add((signal.side,trade.exit_reason))
                first = next(iter(signals.values()))
                with patch('trading.tested_strategy_research._emitted',set()):
                    from trading.tested_strategy_research import evaluate_tested_research
                    candidates = evaluate_tested_research(frame([b for b in bars if b.timestamp<=first.timestamp]),
                        'META',[fvg_exit.STRATEGY_ID],scope='fvg-parity',now=first.timestamp+timedelta(minutes=5))
                self.assertEqual(1,len(candidates))
                self.assertEqual(seed(),candidates[0].meta['authored_exit_state'])
                self.assertEqual(fvg_exit.PROTOCOL,candidates[0].meta['authored_exit_protocol'])
                self.assertEqual((first.stop,first.target),(candidates[0].meta['underlying_stop'],candidates[0].meta['underlying_target']))
        self.assertTrue({(side,reason) for side in (Side.LONG,Side.SHORT) for reason in ('stop','target')}.issubset(seen))
