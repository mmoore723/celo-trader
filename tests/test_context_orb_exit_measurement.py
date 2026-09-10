from datetime import datetime
import unittest
from unittest.mock import patch

from strategy_health import context_orb_exit as module
from tests.test_impulse_exit_measurement import candles
from tests.test_context_strategy_observers import _nr7_frame
from strategies import context_strategy_observers as observers


def meta():
    return {**module.metadata(module.STRATEGY_ID),'or_midpoint':98}


class ContextOrbExitMeasurementTests(unittest.TestCase):
    def detect(self,data=None,**changes):
        args=dict(entry_at='2026-09-10T10:05',entry_quote_at='2026-09-10T10:05:01',
                  direction='bullish',meta=meta(),now='2026-09-10T10:07')
        args.update(changes)
        return module.first_exit(candles('2026-09-10T10:05',350) if data is None else data,**args)

    def test_close_not_wick_and_skip_entry(self):
        data=candles('2026-09-10T10:05',350)
        data.loc[0,['low','close']]=[96,97]
        data.loc[1,'low']=90
        self.assertIsNone(self.detect(data))
        data.loc[1,'close']=98
        self.assertIsNone(self.detect(data,now='2026-09-10T10:06:59'))
        self.assertEqual((datetime(2026,9,10,10,7),'or_midpoint_close'),self.detect(data))
        data.loc[1,['high','close']]=[103,102]
        self.assertEqual('or_midpoint_close',self.detect(data,direction='bearish',meta={**meta(),'or_midpoint':102})[1])

    def test_original_1555_not_1600_fallback(self):
        self.assertIsNone(self.detect(now='2026-09-10T15:54:59'))
        self.assertEqual((datetime(2026,9,10,15,55),'eod_1555_cap'),self.detect(now='2026-09-10T15:55'))

    def test_missing_candles_block_premium_credit_immediately(self):
        data=candles('2026-09-10T10:05',350).drop(index=1)
        self.assertEqual('waiting_for_bars',self.detect(data)[1])
        self.assertEqual('missing_bars',self.detect(data,now='2026-09-10T10:13')[1])

    def test_invalid_metadata_and_late_entry(self):
        self.assertEqual('missing_exit_state',self.detect(meta={})[1])
        self.assertEqual('invalid_levels',self.detect(meta={**meta(),'or_midpoint':float('nan')})[1])
        self.assertEqual('late_entry_quote',self.detect(entry_quote_at='2026-09-10T10:06')[1])

    def test_actual_nr7_signal_stamped_only_at_research_boundary(self):
        today,now=_nr7_frame()
        with patch.object(observers,'_emitted',set()):
            signal=observers.evaluate_orb_nr7_inside(today,ticker='TSLA',now=now)
        self.assertIsNotNone(signal)
        original=dict(signal.meta)
        from trading.entry.candidate_observation import observe_candidate_contract
        with patch('trading.entry.candidate_observation.record_router_candidate') as record:
            observe_candidate_contract(ticker='META',signal=signal,underlying_price=101,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=True)
        self.assertEqual(module.PROTOCOL,record.call_args.args[1].meta['authored_exit_protocol'])
        self.assertEqual(original['or_midpoint'],signal.meta['or_midpoint'])
        with patch.object(observers,'_emitted',set()):
            execution=observers.evaluate_orb_nr7_inside(today,ticker='TSLA',now=now)
        with patch('trading.entry.candidate_observation.record_router_candidate'):
            observe_candidate_contract(ticker='TSLA',signal=execution,underlying_price=101,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=False)
        self.assertNotIn('authored_exit_protocol',execution.meta)
