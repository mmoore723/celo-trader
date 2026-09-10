from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from strategy_health import context_vwap_exit as exits
from tests.test_context_vwap_exit import session
from tests.test_context_strategy_observers import _vwap_displacement_frame
from strategies import context_strategy_observers as source
from trading.vwap_displacement_exit import evaluate_vwap_displacement_exit


class DisplacementExitMeasurementTests(unittest.TestCase):
    def detect(self,frame,**changes):
        args=dict(entry_at='2026-09-10T10:35',entry_quote_at='2026-09-10T10:35:03',
                  direction='bullish',meta={**exits.metadata(exits.DISPLACEMENT_STRATEGY_ID),'previous_high':104},
                  now='2026-09-10T10:37',strategy_id=exits.DISPLACEMENT_STRATEGY_ID)
        return exits.first_exit(frame,**{**args,**changes})

    def test_genuine_displacement_signal_gets_distinct_research_proof(self):
        from trading.cross_ticker_shadow import evaluate_bar_strategy
        from trading.entry.candidate_observation import observe_candidate_contract
        frame,now=_vwap_displacement_frame()
        def evaluate(data,**kwargs):
            return source.evaluate_vwap_displacement(data,now=now,**kwargs)
        with patch.object(source,'_emitted',set()):
            signal=evaluate_bar_strategy(exits.DISPLACEMENT_STRATEGY_ID,evaluate,frame,ticker='META',account_scope='a')
            execution=evaluate(frame,ticker='TSLA')
        self.assertIsNotNone(signal)
        self.assertTrue(signal.meta['displacement_at_1030'])
        with patch('trading.entry.candidate_observation.record_router_candidate') as record:
            observe_candidate_contract(ticker='META',signal=signal,underlying_price=102.2,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=True)
        self.assertEqual('META',record.call_args.args[0])
        self.assertEqual(exits.DISPLACEMENT_PROTOCOL,signal.meta['authored_exit_protocol'])
        with patch('trading.entry.candidate_observation.record_router_candidate'):
            observe_candidate_contract(ticker='TSLA',signal=execution,underlying_price=102.2,tradier=None,
                                       balance=5000,risk=None,settings={},research_only=False)
        self.assertNotIn('authored_exit_protocol',execution.meta)

    def test_source_hashes_match_reviewed_v020_not_ker_proof(self):
        proof=json.loads((Path(__file__).parents[1]/'config/strategy_evidence/ctx_vwap_displacement-0.2.0.json').read_text())
        self.assertEqual(proof['implementation_sha256_at_review'],exits.engine_hash())
        expected=next(s['sha256'] for s in proof['runtime_policy_sources'] if s['path']=='trading/vwap_displacement_exit.py')
        self.assertEqual(expected,exits.displacement_exit_hash())
        self.assertEqual('missing_exit_state',self.detect(session(),meta=exits.metadata(exits.STRATEGY_ID))[1])
        self.assertEqual('invalid_direction',self.detect(session(),direction='bearish')[1])

    def test_complete_data_exit_parity_with_execution_source(self):
        scenarios=[('target',66,104,'prior_high_target','vwap_displacement_prior_high_target','10:37'),
                   ('stop',69,96,'five_minute_close_below_vwap','vwap_displacement_5m_close_below_vwap','10:40'),
                   ('cap',0,100,'eod_1555_cap','vwap_displacement_eod_1555','15:55')]
        for kind,index,value,reason,execution_reason,clock in scenarios:
            with self.subTest(kind=kind):
                frame=session()
                if kind=='target': frame.loc[index,'high']=value
                if kind=='stop': frame.loc[index,['low','close']]=[value-1,value]
                now=datetime.fromisoformat('2026-09-10T'+clock)
                five=frame.set_index('time').resample('5min').agg(dict(open='first',high='max',low='min',close='last',volume='sum')).reset_index()
                actual=evaluate_vwap_displacement_exit('2026-09-10T10:35:03',now,
                    one_minute_bars=frame,five_minute_bars=five,strategy_context={'previous_high':104})
                self.assertEqual((True,execution_reason),actual)
                self.assertEqual((now,reason),self.detect(frame,now=now))

    def test_entry_minute_and_missing_structure_differences_are_explicit(self):
        frame=session(); frame.loc[65,'high']=104
        self.assertIsNone(self.detect(frame))
        # Execution retains its emergency 90-minute exit. Missing research
        # candles cannot establish which earlier structural exit happened.
        self.assertEqual('missing_bars',self.detect(frame.iloc[0:0],now='2026-09-10T12:05')[1])
        self.assertEqual((True,'vwap_displacement_missing_structure_90m_safety'),
            evaluate_vwap_displacement_exit('2026-09-10T10:35',datetime(2026,9,10,12,5),
                one_minute_bars=None,five_minute_bars=None,strategy_context={'previous_high':104}))
