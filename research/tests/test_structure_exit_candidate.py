import unittest
from datetime import datetime, timedelta
from research.engine.models import Bar
from research.jobs.structure_exit_candidate import MarketContext, ExitState, ET


class StructureExitTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026,9,10,11,0,tzinfo=ET)

    def state(self, direction=1):
        return ExitState(direction, 100, 100-direction, 5, self.start, 30)

    def context(self, minute=1, close=100, direction=1):
        good = dict(close=100+direction, fast=100+direction, slow=100,
                    histogram=direction, histogram_change=direction, rsi=50+10*direction)
        return dict(time=self.start+timedelta(minutes=minute), close=close,
                    open=close-direction*.1, relative_volume=1,
                    supports=[100.5], resistances=[99.5],
                    frames={n:dict(good) for n in (1,5,15,60)})

    def test_retest_then_reclaim_holds_both_directions(self):
        for d in (1,-1):
            s = self.state(d)
            self.assertEqual('allow_retest', s.step(self.context(close=100-1.1*d,direction=d), 5)['action'])
            self.assertEqual('hold', s.step(self.context(2,100,d), 5)['action'])
            self.assertIsNone(s.broken_at)

    def test_unreclaimed_break_exits_after_two_minutes(self):
        for d in (1,-1):
            s = self.state(d)
            for n in (1,2):
                self.assertEqual('allow_retest', s.step(self.context(n,100-1.1*d,d), 5)['action'])
            self.assertEqual('structure_retest_failed', s.step(self.context(3,100-1.1*d,d), 5)['reason'])

    def test_volume_and_multiframe_failure_exits_immediately(self):
        s = self.state()
        ctx = self.context(close=98.9, direction=-1)
        ctx['relative_volume'] = 2
        self.assertEqual('structure_failed_with_opposing_volume', s.step(ctx,5)['reason'])

    def test_tightening_never_loosens_and_is_direction_symmetric(self):
        for d in (1,-1):
            s = self.state(d)
            self.assertEqual('tighten',s.step(self.context(1,100+1.5*d,d),5)['action'])
            self.assertEqual(100+.5*d,s.protection)
            c = self.context(2,100+1.5*d,d)
            c['supports'],c['resistances'] = [99], [101]
            s.step(c,5)
            self.assertEqual(100+.5*d,s.protection)

    def test_maximum_loss_guard_precedes_missing_indicators_and_timer(self):
        s = self.state()
        c = self.context(30)
        c['frames'] = {}
        self.assertEqual('maximum_premium_loss_20pct',s.step(c,4)['reason'])

    def test_timer_preserved_even_without_indicator_warmup(self):
        s = self.state()
        c = self.context(30)
        c['frames'] = {}
        self.assertEqual('original_time_cap',s.step(c,5)['reason'])

    def test_unknown_context_not_treated_as_agreement(self):
        c = self.context()
        c['frames'][60] = None
        self.assertEqual('missing_context',self.state().step(c,5)['action'])

    def test_duplicate_decisions_rejected(self):
        s = self.state()
        s.step(self.context(),5)
        with self.assertRaises(ValueError):
            s.step(self.context(),5)

    def bars(self):
        start = self.start.replace(hour=9,minute=30)
        return tuple(Bar(start+timedelta(minutes=n),100,101,99,100,100) for n in range(90))

    def test_future_bars_do_not_change_context(self):
        bars = self.bars()
        at = bars[59].timestamp+timedelta(minutes=1)
        future = tuple(Bar(b.timestamp,200,210,190,200,90000) for b in bars[60:])
        self.assertEqual(MarketContext(bars[:60]).at(at),MarketContext(bars[:60]+future).at(at))

    def test_missing_minute_discards_higher_frame_and_rejects_recent_gap(self):
        bars = self.bars()
        market = MarketContext(bars[:56]+bars[57:])
        self.assertEqual(0,len(market.frames[60]))
        with self.assertRaisesRegex(ValueError,'Missing recent'):
            market.at(bars[60].timestamp)

    def test_partial_hour_is_not_used(self):
        market = MarketContext(self.bars()[:59])
        self.assertEqual(0,len(market.frames[60]))

    def test_duplicate_and_invalid_bars_rejected(self):
        bars = self.bars()
        with self.assertRaises(ValueError):
            MarketContext((bars[0],bars[0]))
        with self.assertRaises(ValueError):
            MarketContext((Bar(bars[0].timestamp,100,90,99,100,1),))


if __name__ == '__main__':
    unittest.main()
