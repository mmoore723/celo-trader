from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.vwap_reversion_rth import VWAPReversionRTH
from strategy_health import reversion_exit
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame


def seed():
    return json.loads(json.dumps(reversion_exit.entry_state(VWAPReversionRTH())))


def setup_bars(direction, outcome):
    # Flat session with a genuine, one-sided lower-band rejection at noon.
    entry=100-2.45*13.1/11.55
    bars=[]
    for i in range(78):
        if i<30:
            o,h,low,c,v=100,100.5,99.5,100,1000000
        elif i==30:
            o,h,low,c,v=100,100,entry-.1,entry,1
        else:
            c=entry+outcome*max(0,i-31)*.2
            o,h,low,v=c,c+.05,c-.05,100
        if direction<0:
            o,h,low,c=200-o,200-low,200-h,200-c
        bars.append(Bar(datetime(2026,9,10,9,30)+timedelta(minutes=5*i),o,h,low,c,v))
    return bars


def minute_frame(bars):
    data=frame(bars)
    data['volume']=[b.volume/5 for b in bars for _ in range(5)]
    return data


class ReversionExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args=dict(entry_at='2026-09-10T10:05',entry_quote_at='2026-09-10T10:05:01',
                  stop=98,target=104,direction='bullish',seed=seed(),now='2026-09-10T10:15')
        args.update(changes)
        return reversion_exit.first_exit(candles('2026-09-10T10:05',355) if data is None else data,**args)

    def test_proof_round_trip_and_config_mismatch(self):
        self.assertEqual(reversion_exit.entry_state(VWAPReversionRTH()),seed())
        self.assertEqual('10:00:00',seed()['config']['entry_start'])
        self.assertEqual(4,seed()['config']['stop_atr'])
        self.assertIsNone(self.detect())
        for invalid in (None,{}, {**seed(),'engine_hash':'mismatch'},
                        {**seed(),'config':{**seed()['config'],'stop_atr':3}}):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])

    def test_entry_candle_skipped_completed_bar_stop_wins_both_directions(self):
        data=candles('2026-09-10T10:05',355)
        data.loc[:4,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[5,['high','low']]=[105,97]
        self.assertIsNone(self.detect(data,now='2026-09-10T10:14:59'))
        for direction,stop,target in [('bullish',98,104),('bearish',104,98)]:
            self.assertEqual((datetime(2026,9,10,10,15),'underlying_stop'),
                             self.detect(data,direction=direction,stop=stop,target=target))

    def test_frozen_target_ignores_later_volume_and_target_precedes_stop(self):
        data=candles('2026-09-10T10:05',355)
        data.loc[5,'high']=105
        data.loc[10,'low']=90
        data['volume']=1e12
        self.assertEqual((datetime(2026,9,10,10,15),'underlying_vwap_target'),
                         self.detect(data,now='2026-09-10T10:25'))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_data_or_late_entry_is_not_a_result(self):
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:10')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T10:05',355).drop(index=6),
                         now='2026-09-10T10:21')[1])

    def test_reference_stops_targets_sessions_and_runtime_metadata_match(self):
        seen=set()
        for direction in (1,-1):
            for outcome in (1,-1,0):
                bars=setup_bars(direction,outcome)
                history,signals=[],{}
                engine=VWAPReversionRTH()
                for bar in bars:
                    history.append(bar)
                    signal=engine.evaluate(history)
                    if signal:
                        signals[signal.timestamp]=signal
                trades=Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,VWAPReversionRTH())
                self.assertEqual(1,len(signals))
                self.assertEqual(1,len(trades))
                trade=trades[0]
                signal=signals[trade.signal_time]
                reasons={'stop':'underlying_stop','target':'underlying_vwap_target','session':'session_flatten'}
                result=reversion_exit.first_exit(minute_frame(bars),entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                    direction='bullish' if signal.side is Side.LONG else 'bearish',now=datetime(2026,9,10,16))
                self.assertEqual((trade.exit_time+timedelta(minutes=5),reasons[trade.exit_reason]),result)
                seen.add((signal.side,trade.exit_reason))
                with patch('trading.tested_strategy_research._emitted',set()):
                    from trading.tested_strategy_research import evaluate_tested_research
                    candidates=evaluate_tested_research(minute_frame(bars[:31]),'META',
                        [reversion_exit.STRATEGY_ID],scope='reversion-parity',now=signal.timestamp+timedelta(minutes=5))
                self.assertEqual(1,len(candidates))
                meta=json.loads(json.dumps(candidates[0].meta))
                self.assertEqual(seed(),meta['authored_exit_state'])
                self.assertEqual(reversion_exit.PROTOCOL,meta['authored_exit_protocol'])
                self.assertAlmostEqual(signal.stop,meta['underlying_stop'])
                self.assertAlmostEqual(signal.target,meta['underlying_target'])
        self.assertEqual({(s,r) for s in (Side.LONG,Side.SHORT) for r in ('stop','target','session')},seen)
