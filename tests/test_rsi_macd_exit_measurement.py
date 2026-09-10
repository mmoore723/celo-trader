from dataclasses import replace
from datetime import datetime, timedelta, time, date
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.orb_rsi_macd import ORBRsiMacdShort, ORBRsiMacdShortConfig
from strategy_health import rsi_macd_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return json.loads(json.dumps(rsi_macd_exit.entry_state(ORBRsiMacdShort())))


def setup_bars(outcome):
    bars=[]
    for i in range(26):
        c=102-.07*i
        bars.append(Bar(datetime(2026,9,9,13,30)+timedelta(minutes=5*i),c,c+.02,c-.02,c,100))
    for i in range(78):
        c=100 if i<3 else 99.85+outcome*.08*max(0,i-4)
        spread=.1 if i<3 else .01
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=5*i),c,c+spread,c-spread,c,100))
    return bars


class RsiMacdExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args=dict(entry_at='2026-09-10T10:05',entry_quote_at='2026-09-10T10:05:01',
                  stop=102,target=96,direction='bearish',seed=seed(),now='2026-09-10T10:15')
        args.update(changes)
        return rsi_macd_exit.first_exit(candles('2026-09-10T10:05',355) if data is None else data,**args)

    def test_proof_roundtrip_and_date_config_are_explicit(self):
        self.assertEqual(rsi_macd_exit.entry_state(ORBRsiMacdShort()),seed())
        self.assertEqual('11:00:00',seed()['config']['entry_deadline'])
        self.assertIsNone(seed()['config']['active_date'])
        cfg=replace(ORBRsiMacdShortConfig(),active_date=date(2026,9,10))
        self.assertEqual('2026-09-10',rsi_macd_exit.config_proof(cfg)['active_date'])
        for invalid in (None,{}, {**seed(),'engine_hash':'mismatch'},
                        rsi_macd_exit.entry_state(ORBRsiMacdShort(cfg))):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])
        self.assertEqual('invalid_levels',self.detect(direction='bullish',stop=96,target=102)[1])

    def test_skip_entry_and_wait_for_complete_candle_with_stop_first(self):
        data=candles('2026-09-10T10:05',355)
        data.loc[:4,'high']=110
        self.assertIsNone(self.detect(data))
        data.loc[5,['high','low']]=[103,95]
        self.assertIsNone(self.detect(data,now='2026-09-10T10:14:59'))
        self.assertEqual((datetime(2026,9,10,10,15),'underlying_stop'),self.detect(data))

    def test_1_5r_target_precedes_later_stop_and_rth_close_is_explicit(self):
        data=candles('2026-09-10T10:05',355)
        data.loc[5,'low']=95
        data.loc[10,'high']=110
        self.assertEqual((datetime(2026,9,10,10,15),'underlying_1_5r_target'),
                         self.detect(data,now='2026-09-10T10:25'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_prices_and_candles_do_not_become_results(self):
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:10')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T10:05',355).drop(index=6),
                         now='2026-09-10T10:21')[1])

    def test_real_bearish_signal_midpoint_target_and_reference_exits(self):
        seen=set()
        for outcome in (1,-1,0):
            bars=setup_bars(outcome)
            signal=ORBRsiMacdShort().evaluate(bars[:30])
            self.assertIsNotNone(signal)
            self.assertEqual(Side.SHORT,signal.side)
            self.assertAlmostEqual(100,signal.stop)
            self.assertAlmostEqual(1.5,(signal.entry_reference-signal.target)/(signal.stop-signal.entry_reference))
            trades=Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,ORBRsiMacdShort())
            self.assertEqual(1,len(trades)); trade=trades[0]
            reasons={'stop':'underlying_stop','target':'underlying_1_5r_target','session':'session_flatten'}
            result=rsi_macd_exit.first_exit(frame(bars),entry_at=trade.entry_time,
                entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                direction='bearish',now=datetime(2026,9,10,16))
            self.assertEqual((trade.exit_time+timedelta(minutes=5),reasons[trade.exit_reason]),result)
            seen.add(trade.exit_reason)
            with patch('trading.tested_strategy_research._emitted',set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates=evaluate_tested_research(frame(bars[:30]),'META',[rsi_macd_exit.STRATEGY_ID],
                    scope='rsi-macd-parity',now=signal.timestamp+timedelta(minutes=5))
            self.assertEqual(1,len(candidates))
            meta=json.loads(json.dumps(candidates[0].meta))
            self.assertEqual(seed(),meta['authored_exit_state'])
            self.assertEqual(rsi_macd_exit.PROTOCOL,meta['authored_exit_protocol'])
            self.assertEqual((signal.stop,signal.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertEqual({'stop','target','session'},seen)

    def test_warmup_and_source_once_per_day_rule_not_silently_removed(self):
        bars=setup_bars(0)
        self.assertIsNone(ORBRsiMacdShort().evaluate(bars[26:30]))
        engine=ORBRsiMacdShort()
        self.assertIsNotNone(engine.evaluate(bars[:30]))
        self.assertIsNone(engine.evaluate(bars[:31]))
