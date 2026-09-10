from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.range_sweep_reclaim import RangeSweepReclaim
from strategy_health import range_sweep_exit as module
from tests.test_impulse_exit_measurement import candles
from tests.test_compression_exit_measurement import frame


def engine():
    return RangeSweepReclaim(module.research_config())


def seed():
    return json.loads(json.dumps(module.entry_state(engine())))


def setup_bars(outcome):
    bars=[]
    for i in range(390):
        if i<30:
            o,h,low,c,v=101,101.05,100.95,101,1000000
        elif i<70:
            c=100+(.02 if i%2 else -.02)
            o,h,low,v=c,c+.05,c-.05,100
        elif i==70:
            o,h,low,c,v=99.85,99.9,99.78,99.82,100
        elif i==71:
            o,h,low,c,v=99.9,99.97,99.88,99.95,100
        else:
            c=99.95+outcome*.05*max(0,i-72)
            o,h,low,v=c,c+.01,c-.01,100
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=i),o,h,low,c,v))
    return bars


class RangeSweepExitMeasurementTests(unittest.TestCase):
    def detect(self,data=None,**changes):
        args=dict(entry_at='2026-09-10T10:42',entry_quote_at='2026-09-10T10:42:01',
                  stop=98,target=104,direction='bullish',seed=seed(),now='2026-09-10T10:44')
        args.update(changes)
        return module.first_exit(candles('2026-09-10T10:42',318) if data is None else data,**args)

    def test_config_proof_matches_deployed_calls_only(self):
        self.assertEqual(30,seed()['config']['range_bars'])
        self.assertEqual(.30,seed()['config']['maximum_efficiency'])
        self.assertEqual(.15,seed()['config']['minimum_sweep_atr'])
        for invalid in (None,{}, {**seed(),'engine_hash':'mismatch'},module.entry_state(RangeSweepReclaim())):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])
        self.assertEqual('invalid_levels',self.detect(direction='bearish',stop=104,target=98)[1])

    def test_skip_entry_and_use_one_minute_close_stop_first(self):
        data=candles('2026-09-10T10:42',318)
        data.loc[0,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[1,['high','low']]=[105,97]
        self.assertIsNone(self.detect(data,now='2026-09-10T10:43:59'))
        self.assertEqual((datetime(2026,9,10,10,44),'underlying_stop'),self.detect(data))

    def test_target_is_frozen_not_recomputed_from_later_volume(self):
        data=candles('2026-09-10T10:42',318)
        data.loc[1,'high']=105
        data.loc[2,'low']=90
        data['volume']=1e12
        self.assertEqual((datetime(2026,9,10,10,44),'underlying_vwap_target'),
                         self.detect(data,now='2026-09-10T10:50'))

    def test_market_close_without_a_75_bar_timer(self):
        self.assertIsNone(self.detect(now='2026-09-10T12:00'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_bars_late_ask_and_invalid_levels_are_not_results(self):
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:43')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T10:42',318).drop(index=1),
                         now='2026-09-10T10:50')[1])

    def test_real_source_and_runtime_call_match_reference_exits(self):
        seen=set()
        for outcome in (-1,1,0):
            bars=setup_bars(outcome)
            source=engine(); signals=[]
            for i in range(72):
                signal=source.evaluate(bars[:i+1])
                if signal: signals.append(signal)
            self.assertEqual(1,len(signals)); signal=signals[0]
            self.assertEqual(Side.LONG,signal.side)
            self.assertAlmostEqual(signal.features['vwap'],signal.target,places=5)
            self.assertFalse(source._long_armed)
            trades=Simulator(SimulationConfig(max_hold_bars=390,session_exit_time=time(15,59))).run(bars,engine())
            self.assertEqual(1,len(trades)); trade=trades[0]
            reasons={'stop':'underlying_stop','target':'underlying_vwap_target','session':'session_flatten'}
            result=module.first_exit(frame(bars),entry_at=trade.entry_time,
                entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                direction='bullish',now=datetime(2026,9,10,16))
            self.assertEqual((trade.exit_time+timedelta(minutes=1),reasons[trade.exit_reason]),result)
            seen.add(trade.exit_reason)
            with patch('trading.tested_strategy_research._emitted',set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates=evaluate_tested_research(frame(bars[:72]),'META',[module.STRATEGY_ID],
                    scope='range-sweep-parity',now=signal.timestamp+timedelta(minutes=1))
            self.assertEqual(1,len(candidates))
            meta=json.loads(json.dumps(candidates[0].meta))
            self.assertEqual(seed(),meta['authored_exit_state'])
            self.assertEqual(module.PROTOCOL,meta['authored_exit_protocol'])
            self.assertEqual((signal.stop,signal.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertEqual({'stop','target','session'},seen)
