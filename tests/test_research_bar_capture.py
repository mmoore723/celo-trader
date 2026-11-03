from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import pandas as pd
from trading.research_bar_capture import session_frame, missing_minutes


def bars(minutes):
    return [{'t': f'2026-11-03T14:{m:02d}:00Z', 'o':100, 'h':101,
             'l':99, 'c':100, 'v':10} for m in minutes]


class BarRecoveryTests(unittest.TestCase):
    def run_case(self, primary, fallback):
        self.p = SimpleNamespace(get_session_bars=Mock(return_value=(primary, False, True)))
        self.f = SimpleNamespace(get_session_bars=Mock(return_value=(fallback, False, True)))
        self.persist = Mock()
        self.clock = lambda: datetime(2026,11,3,9,33)
        return session_frame(self.p,self.f,'COIN',account='paper-A',clock=self.clock,persist=self.persist,prefer_consolidated=False)

    def test_direct_complete_feed_cached_only_within_minute_and_scope(self):
        from trading.research_bar_capture import _complete
        _complete.clear()
        primary=SimpleNamespace(get_session_bars=Mock(return_value=(bars([30]),False,True)))
        consolidated=SimpleNamespace(get_session_bars=Mock(return_value=(bars([30,31,32,33]),False,True)))
        persist=Mock()
        now=datetime(2026,11,3,9,33)
        def read(account='A'):
            return session_frame(primary,consolidated,'COIN',account=account,clock=lambda:now,persist=persist)
        first=read(); self.assertEqual(3,len(first))
        first.loc[0,'close']=999
        self.assertNotEqual(999,read().iloc[0]['close'])
        self.assertEqual(1,consolidated.get_session_bars.call_count)
        primary.get_session_bars.assert_not_called()
        read('B'); self.assertEqual(2,consolidated.get_session_bars.call_count)
        now=datetime(2026,11,3,9,34)
        self.assertEqual(4,len(read()))
        self.assertEqual(3,consolidated.get_session_bars.call_count)
        self.assertEqual([],persist.call_args.kwargs['missing'])
        self.assertEqual('tradier_session_1m_direct_v2',persist.call_args.kwargs['fallback'].attrs['source'])

    def test_direct_failure_uses_existing_recovery_without_inventing_bars(self):
        from trading.research_bar_capture import _complete
        _complete.clear()
        primary=SimpleNamespace(get_session_bars=Mock(return_value=(bars([30,31,32]),False,True)))
        consolidated=SimpleNamespace(get_session_bars=Mock(side_effect=TimeoutError('timeout')))
        result=session_frame(primary,consolidated,'COIN',account='A',clock=lambda:datetime(2026,11,3,9,33),persist=Mock())
        self.assertEqual(3,len(result))
        self.assertFalse(_complete)

    def test_complete_primary_does_not_request_fallback(self):
        frame=self.run_case(bars([30,31,32]),[])
        self.assertEqual(3,len(frame));self.f.get_session_bars.assert_not_called()
        self.persist.assert_not_called()

    def test_sparse_primary_recovers_with_original_receipt_evidence(self):
        frame=self.run_case(bars([30,32]),bars([30,31,32]))
        self.assertEqual([],missing_minutes(frame,self.clock()))
        self.assertTrue(self.persist.call_args.kwargs['accepted'])
        self.assertEqual('paper-A',self.persist.call_args.kwargs['account'])
        self.assertEqual(1,len(self.persist.call_args.kwargs['missing']))
        self.assertIn('received_at',frame.attrs)

    def test_incomplete_fallback_never_fabricates_minutes(self):
        frame=self.run_case(bars([30]),bars([30,32]))
        self.assertEqual(2,len(frame));self.assertTrue(self.persist.call_args.kwargs['accepted'])
        self.assertFalse(frame.attrs['coverage_complete'])
        self.assertEqual([datetime(2026,11,3,9,31)],missing_minutes(frame,self.clock()))
        self.assertEqual('tradier_session_1m_partial_recovery_v1',frame.attrs['source'])

    def test_replacement_cannot_lose_existing_minutes(self):
        frame=self.run_case(bars([31]),bars([30,32]))
        self.assertEqual(1,len(frame))
        self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_same_sparse_coverage_is_not_a_recovery(self):
        self.run_case(bars([30]),bars([30]))
        self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_invalid_partial_candles_rejected(self):
        bad=bars([30,32]);bad[1]['l']=105
        self.run_case(bars([30]),bad)
        self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_previous_session_and_duplicate_fallback_rejected(self):
        for fallback in (bars([30,30,31,32]),[{**b,'t':b['t'].replace('11-03','11-02')} for b in bars([30,31,32])]):
            self.run_case(bars([30]),fallback)
            self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_only_completed_minutes_required(self):
        self.assertEqual(3,len(self.run_case(bars([30,31,32]),[])))
        self.assertEqual([],missing_minutes(pd.DataFrame(),datetime(2026,11,3,9,29)))
