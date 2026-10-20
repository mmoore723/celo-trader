from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch, Mock

import pandas as pd

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.afternoon_compression_breakout import AfternoonCompressionBreakout
from strategy_health import compression_exit as module
from tests.test_impulse_exit_measurement import candles


def engine():
    return AfternoonCompressionBreakout(module.research_config())


def seed():
    return json.loads(json.dumps(module.entry_state(engine())))


def setup_bars(direction, outcome):
    bars=[]
    for i in range(390):
        c=100 if i<225 else 100+direction*(.2+outcome*.02*max(0,i-226))
        spread=.05 if i<225 else .01
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=i),c,c+spread,c-spread,c,100))
    return bars


def frame(bars):
    return pd.DataFrame([dict(time=b.timestamp,open=b.open,high=b.high,low=b.low,
                              close=b.close,volume=b.volume) for b in bars])


class CompressionExitMeasurementTests(unittest.TestCase):
    def test_289_missing_minutes_retry_real_consolidated_bars(self):
        data=candles('2026-10-12T14:01',11)
        for col in ('open','high','low','close'):
            data[col]=745.7
        sparse=data.drop(index=[4,9])
        args=dict(entry_at='2026-10-12T14:01',entry_quote_at='2026-10-12T14:01:50.762278',
                  stop=747.22,target=741.91,direction='bearish',seed=seed(),now='2026-10-12T14:11:01')
        self.assertEqual(module.first_exit(sparse,**args)[1],'missing_bars')
        lookup=Mock(return_value=data)
        self.assertIsNone(module.first_exit(sparse,**args,repair_lookup=lookup))
        lookup.assert_called_once()
        early={**args,'now':'2026-10-12T14:06:00'}
        early_lookup=Mock(return_value=data)
        self.assertIsNone(module.first_exit(sparse,**early,repair_lookup=early_lookup))
        early_lookup.assert_called_once()
        data.loc[5,'high']=748
        self.assertEqual(module.first_exit(sparse,**args,repair_lookup=lambda:data),
                         (datetime(2026,10,12,14,7),'underlying_stop'))

    def test_repair_failure_keeps_safety_exit_and_complete_data_skips_io(self):
        data=candles('2026-09-10T13:16',164)
        lookup=Mock(side_effect=TimeoutError())
        self.assertIsNone(self.detect(data,repair_lookup=lookup))
        lookup.assert_not_called()
        sparse=data.drop(index=1)
        self.assertEqual(self.detect(sparse,now='2026-09-10T13:24',repair_lookup=lookup)[1],'missing_bars')
        for replacement in (sparse, data.assign(time=data.time-pd.Timedelta(days=1)),
                            pd.concat([data,data]), data.assign(high=float('nan'))):
            self.assertEqual(self.detect(sparse,now='2026-09-10T13:24',
                                        repair_lookup=lambda:replacement)[1],'missing_bars')

    def detect(self, data=None, **changes):
        args=dict(entry_at='2026-09-10T13:16',entry_quote_at='2026-09-10T13:16:01',
                  stop=98,target=104,direction='bullish',seed=seed(),now='2026-09-10T13:18')
        args.update(changes)
        return module.first_exit(candles('2026-09-10T13:16',164) if data is None else data,**args)

    def test_runtime_config_proof_not_class_defaults(self):
        self.assertEqual(.004,seed()['config']['max_compression_pct'])
        self.assertEqual('15:00:00',seed()['config']['entry_end'])
        self.assertEqual(module.entry_state(engine()),seed())
        for invalid in (None,{}, {**seed(),'engine_hash':'mismatch'},
                        module.entry_state(AfternoonCompressionBreakout())):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])

    def test_one_minute_boundary_skip_entry_and_stop_wins_ambiguity(self):
        data=candles('2026-09-10T13:16',164)
        data.loc[0,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[1,['high','low']]=[105,97]
        self.assertIsNone(self.detect(data,now='2026-09-10T13:17:59'))
        self.assertEqual((datetime(2026,9,10,13,18),'underlying_stop'),self.detect(data))

    def test_target_before_later_stop(self):
        data=candles('2026-09-10T13:16',164)
        data.loc[1,'high']=105
        data.loc[2,'low']=90
        self.assertEqual((datetime(2026,9,10,13,18),'underlying_2r_target'),
                         self.detect(data,now='2026-09-10T13:30'))

    def test_no_75_minute_cap_and_session_close(self):
        self.assertIsNone(self.detect(now='2026-09-10T14:40'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_entry_quote_must_precede_first_observed_minute(self):
        for stamp in ('2026-09-10T13:15:59','2026-09-10T13:17','2026-09-10T13:20'):
            self.assertEqual('late_entry_quote',self.detect(entry_quote_at=stamp)[1])
        self.assertIsNone(self.detect(entry_quote_at='2026-09-10T13:16:59'))

    def test_missing_and_invalid_data_do_not_become_results(self):
        data=candles('2026-09-10T13:16',164).drop(index=1)
        self.assertEqual('missing_bars',self.detect(data,now='2026-09-10T13:24')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('duplicate_bars',self.detect(pd.concat([data,data]))[1])

    def test_genuine_both_direction_signals_and_six_reference_exits(self):
        seen=set()
        for direction in (1,-1):
            for outcome in (-1,1,0):
                bars=setup_bars(direction,outcome)
                source=engine(); signal=None
                for i in range(226):
                    signal=source.evaluate(bars[:i+1])
                self.assertIsNotNone(signal)
                self.assertEqual(Side.LONG if direction==1 else Side.SHORT,signal.side)
                self.assertAlmostEqual(2,abs(signal.target-signal.entry_reference)/abs(signal.stop-signal.entry_reference))
                self.assertIsNone(source.evaluate(bars[:227]))
                trades=Simulator(SimulationConfig(max_hold_bars=390,session_exit_time=time(15,59))).run(bars,engine())
                self.assertEqual(1,len(trades)); trade=trades[0]
                reasons={'stop':'underlying_stop','target':'underlying_2r_target','session':'session_flatten'}
                result=module.first_exit(frame(bars),entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                    direction='bullish' if direction==1 else 'bearish',now=datetime(2026,9,10,16))
                self.assertEqual((trade.exit_time+timedelta(minutes=1),reasons[trade.exit_reason]),result)
                seen.add((direction,trade.exit_reason))
                with patch('trading.tested_strategy_research._emitted',set()):
                    from trading.tested_strategy_research import evaluate_tested_research
                    candidates=evaluate_tested_research(frame(bars[:226]),'META',[module.STRATEGY_ID],
                        scope='compression-parity',now=signal.timestamp+timedelta(minutes=1))
                self.assertEqual(1,len(candidates))
                meta=json.loads(json.dumps(candidates[0].meta))
                self.assertEqual(seed(),meta['authored_exit_state'])
                self.assertEqual(module.PROTOCOL,meta['authored_exit_protocol'])
                self.assertEqual((signal.stop,signal.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertEqual(6,len(seen))
