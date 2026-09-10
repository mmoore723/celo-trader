from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.afternoon_reversal import AfternoonReversal
from strategy_health import afternoon_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return json.loads(json.dumps(afternoon_exit.entry_state(AfternoonReversal())))


def setup_bars(direction, outcome):
    anchors = [(0,100),(10,97),(18,99),(26,98),(34,100),(39,99),(42,101)]
    bars = []
    for i in range(78):
        if i > 42:
            price = 101+outcome*max(0,i-43)*.6
        else:
            left,right = next((a,b) for a,b in zip(anchors,anchors[1:]) if a[0]<=i<=b[0])
            price = left[1]+(right[1]-left[1])*(i-left[0])/(right[0]-left[0])
        price = price if direction > 0 else 200-price
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=5*i),price,price+.05,price-.05,price))
    return bars


class AfternoonExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args = dict(entry_at='2026-09-10T13:05',entry_quote_at='2026-09-10T13:05:01',
                    stop=98,target=104,direction='bullish',seed=seed(),now='2026-09-10T13:15')
        args.update(changes)
        return afternoon_exit.first_exit(candles('2026-09-10T13:05',175) if data is None else data,**args)

    def test_proof_round_trip_preserves_time_values(self):
        proof = afternoon_exit.entry_state(AfternoonReversal())
        self.assertEqual(proof,seed())
        self.assertEqual('13:00:00',seed()['config']['start_time'])
        self.assertEqual('15:00:00',seed()['config']['end_time'])
        self.assertIsNone(self.detect())
        for invalid in (None,{}, {**seed(),'engine_hash':'mismatch'},
                        {**seed(),'config':{**seed()['config'],'start_time':'12:00:00'}}):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])

    def test_entry_candle_skipped_and_completed_bar_stop_wins(self):
        data = candles('2026-09-10T13:05',175)
        data.loc[:4,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[5,['high','low']]=[105,97]
        self.assertIsNone(self.detect(data,now='2026-09-10T13:14:59'))
        for direction,stop,target in [('bullish',98,104),('bearish',104,98)]:
            self.assertEqual((datetime(2026,9,10,13,15),'underlying_stop'),
                self.detect(data,direction=direction,stop=stop,target=target))

    def test_target_precedes_later_stop_and_session_close_is_causal(self):
        data=candles('2026-09-10T13:05',175)
        data.loc[5,'high']=105
        data.loc[10,'low']=90
        self.assertEqual((datetime(2026,9,10,13,15),'underlying_2r_target'),
                         self.detect(data,now='2026-09-10T13:25'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_data_or_late_entry_is_not_a_result(self):
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T13:10')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T13:05',175).drop(index=6),
                         now='2026-09-10T13:21')[1])

    def test_all_reference_exits_and_runtime_metadata_match(self):
        seen=set()
        for direction in (1,-1):
            for outcome in (1,-1,0):
                bars=setup_bars(direction,outcome)
                history,signals=[],{}
                engine=AfternoonReversal()
                for bar in bars:
                    history.append(bar)
                    signal=engine.evaluate(history)
                    if signal:
                        signals[signal.timestamp]=signal
                trades=Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,AfternoonReversal())
                self.assertGreater(len(trades),0)
                reasons={'stop':'underlying_stop','target':'underlying_2r_target','session':'session_flatten','time':'time_cap_75bars'}
                for trade in trades:
                    signal=signals[trade.signal_time]
                    result=afternoon_exit.first_exit(frame(bars),entry_at=trade.entry_time,
                        entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                        direction='bullish' if signal.side is Side.LONG else 'bearish',now=datetime(2026,9,10,16))
                    self.assertEqual((trade.exit_time+timedelta(minutes=5),reasons[trade.exit_reason]),result)
                    seen.add((signal.side,trade.exit_reason))
                first=next(iter(signals.values()))
                with patch('trading.tested_strategy_research._emitted',set()):
                    from trading.tested_strategy_research import evaluate_tested_research
                    candidates=evaluate_tested_research(frame([b for b in bars if b.timestamp<=first.timestamp]),
                        'META',[afternoon_exit.STRATEGY_ID],scope='afternoon-parity',now=first.timestamp+timedelta(minutes=5))
                self.assertEqual(1,len(candidates))
                meta=json.loads(json.dumps(candidates[0].meta))
                self.assertEqual(seed(),meta['authored_exit_state'])
                self.assertEqual(afternoon_exit.PROTOCOL,meta['authored_exit_protocol'])
                self.assertEqual((first.stop,first.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertTrue({(s,r) for s in (Side.LONG,Side.SHORT) for r in ('stop','target','session')}.issubset(seen))
