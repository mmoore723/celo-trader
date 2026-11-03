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
        return session_frame(self.p,self.f,'COIN',account='paper-A',clock=self.clock,persist=self.persist)

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
        self.assertEqual(1,len(frame));self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_previous_session_and_duplicate_fallback_rejected(self):
        for fallback in (bars([30,30,31,32]),[{**b,'t':b['t'].replace('11-03','11-02')} for b in bars([30,31,32])]):
            self.run_case(bars([30]),fallback)
            self.assertFalse(self.persist.call_args.kwargs['accepted'])

    def test_only_completed_minutes_required(self):
        self.assertEqual(3,len(self.run_case(bars([30,31,32]),[])))
        self.assertEqual([],missing_minutes(pd.DataFrame(),datetime(2026,11,3,9,29)))
