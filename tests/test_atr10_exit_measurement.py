from datetime import datetime
import unittest
from unittest.mock import patch

import pandas as pd

from strategies import context_strategy_observers as observers
from strategy_health import context_orb_exit as exits
from strategy_router.indicator_frame import _build_indicator_frame
from tests.test_context_strategy_observers import _row
from tests.test_impulse_exit_measurement import candles


def atr_frame(prior_days=10, short=False):
    sessions = pd.bdate_range('2026-08-01', periods=prior_days+1)
    rows = []
    for index, session in enumerate(sessions[:-1]):
        narrow = index == prior_days-1
        for offset in range(0,390,5):
            rows.append(_row(session+pd.Timedelta(hours=9,minutes=30+offset),
                             high=100.5 if narrow else 102, low=99.5 if narrow else 98))
    for offset in range(21):
        values = dict(close=99,low=98.8,high=100.1,volume=200) if short else dict(close=101,high=101.2,volume=200)
        rows.append(_row(sessions[-1]+pd.Timedelta(hours=9,minutes=30+offset),**(values if offset==20 else {})))
    return _build_indicator_frame(pd.DataFrame(rows)), sessions[-1]+pd.Timedelta(hours=10)


class Atr10ExitMeasurementTests(unittest.TestCase):
    def test_actual_long_breakout_requires_ten_prior_sessions(self):
        with patch.object(observers,'_emitted',set()):
            frame, now = atr_frame()
            signal = observers.evaluate_orb_atr10(frame,ticker='SPY',now=now)
            self.assertIsNotNone(signal)
            self.assertEqual(exits.ATR10_STRATEGY_ID,signal.strategy_id)
            self.assertEqual('bullish',signal.direction)
            self.assertEqual(1,signal.meta['prior_range'])
            self.assertEqual(3.7,signal.meta['atr10'])
            frame, now = atr_frame(9)
            self.assertIsNone(observers.evaluate_orb_atr10(frame,ticker='SPY',now=now))

    def test_original_source_has_no_short_breakout(self):
        frame,now=atr_frame(short=True)
        with patch.object(observers,'_emitted',set()):
            self.assertIsNone(observers.evaluate_orb_atr10(frame,ticker='SPY',now=now))

    def test_cross_ticker_signal_gets_atr_proof_only_in_research(self):
        from trading.cross_ticker_shadow import evaluate_bar_strategy
        from trading.entry.candidate_observation import observe_candidate_contract
        frame,now=atr_frame()
        def evaluate(data,**kwargs):
            return observers.evaluate_orb_atr10(data,now=now,**kwargs)
        with patch.object(observers,'_emitted',set()):
            signal=evaluate_bar_strategy(exits.ATR10_STRATEGY_ID,evaluate,frame,ticker='META',account_scope='a')
            execution=observers.evaluate_orb_atr10(frame,ticker='SPY',now=now)
        self.assertIsNotNone(signal)
        with patch('trading.entry.candidate_observation.record_router_candidate') as record:
            observe_candidate_contract(ticker='META',signal=signal,underlying_price=101,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=True)
        self.assertEqual('META',record.call_args.args[0])
        self.assertEqual(exits.ATR10_PROTOCOL,signal.meta['authored_exit_protocol'])
        with patch('trading.entry.candidate_observation.record_router_candidate'):
            observe_candidate_contract(ticker='SPY',signal=execution,underlying_price=101,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=False)
        self.assertNotIn('authored_exit_protocol',execution.meta)

    def test_atr_direction_and_source_proof_are_enforced_without_changing_nr7(self):
        data=candles('2026-09-10T10:05',350)
        args=dict(entry_at='2026-09-10T10:05',entry_quote_at='2026-09-10T10:05:01',
                  now='2026-09-10T10:07',direction='bullish',strategy_id=exits.ATR10_STRATEGY_ID,
                  meta={**exits.metadata(exits.ATR10_STRATEGY_ID),'or_midpoint':98})
        self.assertIsNone(exits.first_exit(data,**args))
        self.assertEqual('invalid_direction',exits.first_exit(data,**{**args,'direction':'bearish'})[1])
        borrowed={**exits.metadata(exits.STRATEGY_ID),'or_midpoint':98}
        self.assertEqual('missing_exit_state',exits.first_exit(data,**{**args,'meta':borrowed})[1])
        self.assertEqual({'engine_hash':exits.engine_hash(),'policy':'midpoint_close_1555_30_100_v1'},
                         exits.metadata(exits.STRATEGY_ID)['authored_exit_state'])
        data.loc[1,['low','close']]=[97,98]
        self.assertEqual((datetime(2026,9,10,10,7),'or_midpoint_close'),exits.first_exit(data,**args))
