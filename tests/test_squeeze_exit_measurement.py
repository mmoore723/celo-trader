from datetime import datetime
import unittest
from unittest.mock import patch
import pandas as pd

from strategy_health import squeeze_exit as exits
from strategies import context_strategy_observers as source
from strategy_router.indicator_frame import _build_indicator_frame
from tests.test_impulse_exit_measurement import candles


def meta():
    return {**exits.metadata(exits.STRATEGY_ID),'sma20':98}


class SqueezeExitMeasurementTests(unittest.TestCase):
    def detect(self,frame=None,**changes):
        args=dict(entry_at='2026-09-10T10:30',entry_quote_at='2026-09-10T10:30:03',
                  direction='bullish',meta=meta(),now='2026-09-10T11:30')
        return exits.first_exit(candles('2026-09-10T10:30',330) if frame is None else frame,**{**args,**changes})

    def test_hourly_close_not_intraminute_or_rolling_average(self):
        frame=candles('2026-09-10T10:30',330)
        frame.loc[20,['low','close']]=[90,91]
        self.assertIsNone(self.detect(frame))
        frame.loc[59,['low','close']]=[96,97]
        self.assertIsNone(self.detect(frame,now='2026-09-10T11:29:59'))
        self.assertEqual((datetime(2026,9,10,11,30),'hourly_close_below_entry_sma20'),self.detect(frame))
        frame.loc[59,'close']=98
        self.assertIsNone(self.detect(frame))

    def test_incomplete_hour_cannot_trigger_before_1555_cap(self):
        frame=candles('2026-09-10T15:30',25)
        frame.loc[24,['low','close']]=[90,91]
        self.assertIsNone(self.detect(frame,entry_at='2026-09-10T15:30',entry_quote_at='2026-09-10T15:30:03',now='2026-09-10T15:54:59'))
        self.assertEqual((datetime(2026,9,10,15,55),'eod_1555_cap'),self.detect(frame,
            entry_at='2026-09-10T15:30',entry_quote_at='2026-09-10T15:30:03',now='2026-09-10T15:55'))

    def test_gap_at_completed_hour_blocks_target_credit(self):
        frame=candles('2026-09-10T10:30',330).drop(index=5)
        self.assertIsNone(self.detect(frame,now='2026-09-10T11:29'))
        self.assertEqual('waiting_for_bars',self.detect(frame)[1])
        self.assertEqual('missing_bars',self.detect(frame,now='2026-09-10T11:36')[1])

    def test_invalid_proof_direction_entry_and_bars(self):
        self.assertEqual('missing_exit_state',self.detect(meta={})[1])
        self.assertEqual('invalid_direction',self.detect(direction='bearish')[1])
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:31')[1])
        self.assertEqual('invalid_entry',self.detect(entry_at='2026-09-10T10:00')[1])
        self.assertEqual('invalid_levels',self.detect(meta={**meta(),'sma20':float('nan')})[1])
        frame=candles('2026-09-10T10:30',330).astype({'close':float}); frame.loc[0,'close']=float('inf')
        self.assertEqual('invalid_bars',self.detect(frame)[1])

    def test_genuine_squeeze_signal_on_actual_meta_frame(self):
        rows=[]
        days=pd.bdate_range('2026-09-01',periods=6)
        for day_index,day in enumerate(days):
            for minute in range(360):
                close=110 if day_index==5 and minute>=300 else 100
                rows.append(dict(time=day+pd.Timedelta(hours=9,minutes=30+minute),
                    open=close,high=close+1,low=close-1,close=close,volume=100))
        frame=_build_indicator_frame(pd.DataFrame(rows))
        now=days[-1]+pd.Timedelta(hours=15,minutes=30)
        from trading.cross_ticker_shadow import evaluate_bar_strategy
        from trading.entry.candidate_observation import observe_candidate_contract
        def evaluate(data,**kwargs): return source.evaluate_squeeze_macd(data,now=now,**kwargs)
        with patch.object(source,'_emitted',set()):
            signal=evaluate_bar_strategy(exits.STRATEGY_ID,evaluate,frame,ticker='META',account_scope='a')
            execution=evaluate(frame,ticker='QQQ')
        self.assertIsNotNone(signal)
        self.assertEqual(now,signal.trigger_bar)
        self.assertEqual(100.5,signal.meta['sma20'])
        self.assertTrue(signal.meta['prior_hour_squeezed'])
        with patch('trading.entry.candidate_observation.record_router_candidate') as record:
            observe_candidate_contract(ticker='META',signal=signal,underlying_price=110,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=True)
        self.assertEqual('META',record.call_args.args[0])
        self.assertEqual(exits.PROTOCOL,signal.meta['authored_exit_protocol'])
        with patch('trading.entry.candidate_observation.record_router_candidate'):
            observe_candidate_contract(ticker='QQQ',signal=execution,underlying_price=110,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=False)
        self.assertNotIn('authored_exit_protocol',execution.meta)
