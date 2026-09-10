from datetime import datetime, timedelta, time
import json
import unittest
from unittest.mock import patch

import pandas as pd
from research.engine.models import Bar, Side
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.strategies.ema_pullback_rth import EMAPullbackRTH
from strategy_health import ema_exit
from tests.test_impulse_exit_measurement import candles


def seed():
    return json.loads(json.dumps(ema_exit.entry_state(EMAPullbackRTH())))


def setup_bars(direction, outcome):
    bars=[]
    day=datetime(2026,8,21,9,30)
    closes=[100+.02*i for i in range(370)]+[104.5,108]+[108+outcome*.7*i for i in range(18)]
    for i,c in enumerate(closes):
        if i and i%26==0:
            day+=timedelta(days=1)
            while day.weekday()>4:
                day+=timedelta(days=1)
        o,h,low=c,c+.2,c-.35
        if direction<0:
            o,h,low,c=200-o,200-low,200-h,200-c
        bars.append(Bar(day+timedelta(minutes=15*(i%26)),o,h,low,c,1500))
    return bars


def minute_frame(bars):
    return pd.DataFrame([dict(time=b.timestamp+timedelta(minutes=i),open=b.open,high=b.high,
                             low=b.low,close=b.close,volume=b.volume/15) for b in bars for i in range(15)])


class EmaExitMeasurementTests(unittest.TestCase):
    def detect(self, data=None, **changes):
        args=dict(entry_at='2026-09-10T10:00',entry_quote_at='2026-09-10T10:00:01',
                  stop=98,target=104,direction='bullish',seed=seed(),now='2026-09-10T10:30')
        args.update(changes)
        return ema_exit.first_exit(candles('2026-09-10T10:00',360) if data is None else data,**args)

    def test_proof_includes_timeframe_and_explicit_close_correction(self):
        self.assertEqual(ema_exit.entry_state(EMAPullbackRTH()),seed())
        self.assertEqual(2.06,seed()['config']['target_risk_ratio'])
        self.assertEqual(15,seed()['timeframe_minutes'])
        for invalid in (None,{}, {**seed(),'timeframe_minutes':5}, {**seed(),'session_policy':'legacy'},
                        {**seed(),'config':{**seed()['config'],'minimum_risk_pct':.001}}):
            self.assertEqual('missing_exit_state',self.detect(seed=invalid)[1])

    def test_entry_interval_skipped_and_no_early_five_minute_exit(self):
        data=candles('2026-09-10T10:00',360)
        data.loc[:14,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[15,['high','low']]=[105,97]
        for stamp in ('10:20','10:25','10:29:59'):
            self.assertIsNone(self.detect(data,now='2026-09-10T'+stamp))
        for direction,stop,target in [('bullish',98,104),('bearish',104,98)]:
            self.assertEqual((datetime(2026,9,10,10,30),'underlying_stop'),
                             self.detect(data,direction=direction,stop=stop,target=target))

    def test_target_and_final_fifteen_minute_bar_close(self):
        data=candles('2026-09-10T10:00',360)
        data.loc[15,'high']=105
        self.assertEqual((datetime(2026,9,10,10,30),'underlying_2_06r_target'),self.detect(data))
        self.assertIsNone(self.detect(now='2026-09-10T15:59:59'))
        self.assertEqual((datetime(2026,9,10,16),'session_flatten'),self.detect(now='2026-09-10T16:00'))

    def test_missing_data_invalid_alignment_and_quote_freshness(self):
        self.assertEqual('invalid_entry',self.detect(entry_at='2026-09-10T10:05')[1])
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:05')[1])
        self.assertEqual('invalid_levels',self.detect(stop=float('nan'))[1])
        self.assertEqual('missing_bars',self.detect(candles('2026-09-10T10:00',360).drop(index=20),
                         now='2026-09-10T10:36')[1])

    def test_genuine_default_signals_and_corrected_reference_exits(self):
        seen=set()
        for direction in (1,-1):
            for outcome in (1,-1,0):
                bars=setup_bars(direction,outcome)
                engine,history,signals=EMAPullbackRTH(),[],{}
                for bar in bars:
                    history.append(bar)
                    signal=engine.evaluate(history)
                    if signal:
                        signals[signal.timestamp]=signal
                # Bar timestamps are opens: 15:45's close is 16:00.
                trades=Simulator(SimulationConfig(session_exit_time=time(15,45))).run(bars,EMAPullbackRTH())
                self.assertGreaterEqual(len(trades),1)
                trade=trades[0]; signal=signals[trade.signal_time]
                reasons={'stop':'underlying_stop','target':'underlying_2_06r_target','session':'session_flatten'}
                result=ema_exit.first_exit(minute_frame(bars),entry_at=trade.entry_time,
                    entry_quote_at=trade.entry_time+timedelta(seconds=1),seed=seed(),stop=signal.stop,target=signal.target,
                    direction='bullish' if signal.side is Side.LONG else 'bearish',now=datetime(2026,9,10,16))
                self.assertEqual((trade.exit_time+timedelta(minutes=15),reasons[trade.exit_reason]),result)
                seen.add((signal.side,trade.exit_reason))
                with patch('trading.tested_strategy_research._emitted',set()):
                    from trading.tested_strategy_research import evaluate_tested_research
                    candidates=evaluate_tested_research(minute_frame(bars[:372]),'META',[ema_exit.STRATEGY_ID],
                        scope='ema-parity',now=signal.timestamp+timedelta(minutes=15))
                self.assertEqual(1,len(candidates))
                meta=json.loads(json.dumps(candidates[0].meta))
                self.assertEqual(seed(),meta['authored_exit_state'])
                self.assertEqual(ema_exit.PROTOCOL,meta['authored_exit_protocol'])
                self.assertEqual((signal.stop,signal.target),(meta['underlying_stop'],meta['underlying_target']))
        self.assertEqual({(s,r) for s in (Side.LONG,Side.SHORT) for r in ('stop','target','session')},seen)

    def test_legacy_runner_misses_session_close_and_must_not_be_relabeled(self):
        bars=setup_bars(1,0)
        bars.append(Bar(datetime(2026,9,11,9,30),108,108.2,107.65,108,1500))
        old=Simulator(SimulationConfig(session_exit_time=time(15,55))).run(bars,EMAPullbackRTH())[0]
        corrected=Simulator(SimulationConfig(session_exit_time=time(15,45))).run(bars,EMAPullbackRTH())[0]
        self.assertEqual(datetime(2026,9,11,9,30),old.exit_time)
        self.assertEqual('end_of_data',old.exit_reason)
        self.assertEqual(datetime(2026,9,10,15,45),corrected.exit_time)
        self.assertEqual('session',corrected.exit_reason)
