from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.midday_breakdown import MiddayBreakdown
from strategy_health import midday_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return json.loads(json.dumps(midday_exit.entry_state(MiddayBreakdown())))


def setup_bars(outcome):
    bars=[]
    for i in range(78):
        price=101 if i<6 else 100 if i<19 else 99.7+outcome*max(0,i-20)*.1
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=5*i),price,price+.1,price-.1,price))
    return bars


class MiddayExitMeasurementTests(unittest.TestCase):
    def detect(self,data=None,**changes):
        args=dict(entry_at='2026-09-10T11:10',entry_quote_at='2026-09-10T11:10:01',
                  stop=104,target=98,direction='bearish',seed=seed(),now='2026-09-10T11:20')
        args.update(changes)
        return midday_exit.first_exit(candles('2026-09-10T11:10',290) if data is None else data,**args)

    def test_time_proof_round_trip_and_short_only_fidelity(self):
        self.assertEqual(seed(),midday_exit.entry_state(MiddayBreakdown()))
        for k,v in {'base_start':'10:00:00','base_end':'11:00:00','entry_start':'11:05:00','entry_end':'13:30:00'}.items():
            self.assertEqual(v,seed()['config'][k])
        self.assertIsNone(self.detect())
        self.assertEqual('invalid_levels',self.detect(direction='bullish',stop=98,target=104)[1])
        for bad in [None,{}, {**seed(),'engine_hash':'different'},
                    {**seed(),'config':{**seed()['config'],'base_end':'10:55:00'}}]:
            self.assertEqual('missing_exit_state',self.detect(seed=bad)[1])

    def test_skips_entry_bar_and_stop_wins_completed_bar_ambiguity(self):
        data=candles('2026-09-10T11:10',290)
        data.loc[:4,'high']=110
        self.assertIsNone(self.detect(data))
        data.loc[5,['high','low']]=[105,97]
        self.assertIsNone(self.detect(data,now='2026-09-10T11:19:59'))
        self.assertEqual((datetime(2026,9,10,11,20),'underlying_stop'),self.detect(data))

    def test_target_is_first_event_and_session_exit_waits_for_close(self):
        data=candles('2026-09-10T11:10',290)
        data.loc[5,'low']=97
        data.loc[10,'high']=110
        self.assertEqual((datetime(2026,9,10,11,20),'underlying_2r_target'),
                         self.detect(data,now='2026-09-10T11:30'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_data_or_late_entry_never_produces_profit(self):
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T11:15')[1])
        self.assertEqual('invalid_levels',self.detect(target=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T11:10',290).drop(index=6),
                         now='2026-09-10T11:26')[1])

    def test_reference_stop_target_session_and_runtime_metadata(self):
        seen=set()
        for outcome in (-1,1,0):
            bars=setup_bars(outcome)
            history,signals=[],{}
            engine=MiddayBreakdown()
            for bar in bars:
                history.append(bar)
                signal=engine.evaluate(history)
                if signal:
                    signals[signal.timestamp]=signal
            trades=Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,MiddayBreakdown())
            self.assertEqual(1,len(trades))
            reasons={'stop':'underlying_stop','target':'underlying_2r_target','session':'session_flatten'}
            for trade in trades:
                signal=signals[trade.signal_time]
                self.assertEqual(Side.SHORT,signal.side)
                result=midday_exit.first_exit(frame(bars),entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                    direction='bearish',now=datetime(2026,9,10,16))
                self.assertEqual((trade.exit_time+timedelta(minutes=5),reasons[trade.exit_reason]),result)
                seen.add(trade.exit_reason)
            first=next(iter(signals.values()))
            with patch('trading.tested_strategy_research._emitted',set()):
                from trading.tested_strategy_research import evaluate_tested_research
                candidates=evaluate_tested_research(frame([b for b in bars if b.timestamp<=first.timestamp]),
                    'META',[midday_exit.STRATEGY_ID],scope='midday-parity',now=first.timestamp+timedelta(minutes=5))
            self.assertEqual(1,len(candidates))
            meta=json.loads(json.dumps(candidates[0].meta))
            self.assertEqual(seed(),meta['authored_exit_state'])
            self.assertEqual(midday_exit.PROTOCOL,meta['authored_exit_protocol'])
            self.assertEqual((first.stop,first.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertEqual({'stop','target','session'},seen)
