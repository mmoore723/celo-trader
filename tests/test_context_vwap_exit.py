from datetime import datetime
import unittest
from unittest.mock import patch
import pandas as pd

from strategy_health import context_vwap_exit as exits
from tests.test_impulse_exit_measurement import candles
from tests.test_context_strategy_observers import _vwap_displacement_frame
from strategy_router.indicator_frame import _build_indicator_frame
from strategies import context_strategy_observers as source


def meta():
    return {**exits.metadata(exits.STRATEGY_ID),'previous_high':104}


def session():
    return candles('2026-09-10T09:30',390).assign(volume=100)


class ContextVwapExitTests(unittest.TestCase):
    def detect(self,frame=None,**changes):
        args=dict(entry_at='2026-09-10T10:05',entry_quote_at='2026-09-10T10:05:03',
                  direction='bullish',meta=meta(),now='2026-09-10T10:07')
        return exits.first_exit(session() if frame is None else frame,**{**args,**changes})

    def test_one_minute_prior_high_after_entry_minute_only(self):
        frame=session(); frame.loc[35,'high']=110
        self.assertIsNone(self.detect(frame))
        frame.loc[36,'high']=104
        self.assertIsNone(self.detect(frame,now='2026-09-10T10:06:59'))
        self.assertEqual((datetime(2026,9,10,10,7),'prior_high_target'),self.detect(frame))

    def test_vwap_uses_completed_five_minute_session_bars_not_entry_level(self):
        frame=session(); frame.loc[39,['low','close']]=[95,96]
        self.assertIsNone(self.detect(frame,now='2026-09-10T10:09:59'))
        self.assertEqual((datetime(2026,9,10,10,10),'five_minute_close_below_vwap'),
                         self.detect(frame,now='2026-09-10T10:10',meta={**meta(),'vwap':1}))
        frame.loc[39,'high']=104
        self.assertEqual('prior_high_target',self.detect(frame,now='2026-09-10T10:10')[1])

    def test_session_history_and_price_volume_are_required(self):
        frame=session().drop(index=2)
        self.assertEqual('missing_bars',self.detect(frame)[1])
        frame=session(); frame.loc[0,'volume']=float('nan')
        self.assertEqual('invalid_bars',self.detect(frame)[1])
        frame=session().drop(index=36)
        self.assertIsNone(self.detect(frame))
        self.assertEqual('missing_bars',self.detect(frame,now='2026-09-10T10:13')[1])

    def test_original_cutoff_metadata_direction_and_late_entry(self):
        self.assertIsNone(self.detect(now='2026-09-10T15:54:59'))
        self.assertEqual((datetime(2026,9,10,15,55),'eod_1555_cap'),self.detect(now='2026-09-10T15:55'))
        self.assertEqual('missing_exit_state',self.detect(meta={})[1])
        self.assertEqual('invalid_direction',self.detect(direction='bearish')[1])
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:06')[1])
        self.assertEqual('invalid_entry',self.detect(entry_at='2026-09-10T10:06')[1])
        self.assertEqual('invalid_levels',self.detect(meta={**meta(),'previous_high':float('nan')})[1])

    def test_session_vwap_weights_five_minute_high_low_close_and_volume(self):
        frame=session()
        frame.loc[0:4,'high']=130
        frame.loc[0:4,'volume']=10000
        # The heavy opening bucket keeps session VWAP above 105. Looking only
        # at the latest bucket or an entry-level VWAP would miss this stop.
        frame.loc[35:39,['open','high','low','close']]=[104,106,104,105]
        self.assertEqual('five_minute_close_below_vwap',self.detect(
            frame,now='2026-09-10T10:10',meta={**meta(),'previous_high':150,'vwap':1})[1])
        frame['volume']=0
        self.assertIsNone(self.detect(frame,now='2026-09-10T10:10',meta={**meta(),'previous_high':150}))

    def test_repeated_and_future_candles(self):
        frame=session()
        self.assertEqual('duplicate_bars',self.detect(pd.concat([frame,frame.iloc[[0]]]))[1])
        frame.loc[38,'high']=200
        self.assertIsNone(self.detect(frame))

    def test_real_ker_signal_across_actual_meta_candles(self):
        today,now=_vwap_displacement_frame()
        prior=[]
        for day_index,day in enumerate(pd.bdate_range('2026-09-01',periods=2)):
            for offset in range(360):
                close=90+(day_index*6+offset//60)*.5
                prior.append(dict(time=day+pd.Timedelta(hours=9,minutes=30+offset),open=close,
                                  high=close+.2,low=close-.2,close=close,volume=100))
        frame=_build_indicator_frame(pd.concat([pd.DataFrame(prior),today],ignore_index=True))
        from trading.cross_ticker_shadow import evaluate_bar_strategy
        from trading.entry.candidate_observation import observe_candidate_contract
        def evaluate(data,**kwargs):
            return source.evaluate_vwap_ker(data,now=now,**kwargs)
        with patch.object(source,'_emitted',set()):
            signal=evaluate_bar_strategy(exits.STRATEGY_ID,evaluate,frame,ticker='META',account_scope='a')
            execution=evaluate(frame,ticker='SPY')
        self.assertIsNotNone(signal)
        self.assertGreater(signal.meta['ker_1h_10'],.60)
        with patch('trading.entry.candidate_observation.record_router_candidate') as record:
            observe_candidate_contract(ticker='META',signal=signal,underlying_price=102.2,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=True)
        self.assertEqual('META',record.call_args.args[0])
        self.assertEqual(exits.PROTOCOL,signal.meta['authored_exit_protocol'])
        with patch('trading.entry.candidate_observation.record_router_candidate'):
            observe_candidate_contract(ticker='SPY',signal=execution,underlying_price=102.2,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=False)
        self.assertNotIn('authored_exit_protocol',execution.meta)
