"""Research-only tests of the frozen loss-rule experiment."""
from datetime import datetime, timedelta, timezone
import unittest
from research.jobs.replay_two_leg_initial_loss import replay, compare

START=datetime(2026,1,5,15,tzinfo=timezone.utc)


def quote(minute,bid='2',ask='2.04',size='1',contract='TSLA test'):
    return dict(contract=contract,time=(START+timedelta(minutes=minute)).isoformat(),
                bid=bid,ask=ask,bid_size=size,ask_size=size)


def entry(exit_bid='2.10'):
    from decimal import Decimal as D
    return dict(date='2026-01-05',contract='TSLA test',entry_time=START.isoformat(),
                entry_ask='2.00',entry_bid='1.96',status='priced',exit_bid=exit_bid,
                exit_time=(START+timedelta(minutes=91)).isoformat(),
                net_pnl_one_contract=str((D(exit_bid)-D('2'))*100-D('3.30')))


def path():
    return [quote(0,'1.96','2.00')]+[quote(n) for n in range(1,91)]+[quote(91,'2.10','2.14')]


class InitialLossReplayTests(unittest.TestCase):
    def test_untriggered_reproduces_control(self):
        r=replay(entry(),path())
        self.assertEqual(r['control'],r['variant'])
        self.assertEqual(r['control']['net'],'6.70')

    def test_exact_threshold_later_fill_and_damaged_winner(self):
        p=path();p[1]=quote(1,'1.60','1.64');p[2]=quote(2,'1.50','1.54')
        r=replay(entry(),p)
        self.assertEqual(r['variant']['net'],'-53.30')
        self.assertEqual(r['variant']['decision_at'],p[1]['time'])
        self.assertEqual(r['variant']['exit_time'],p[2]['time'])
        self.assertEqual(compare([r])['winners_to_losers'],1)

    def test_no_fill_at_trigger_or_after_window(self):
        p=path();p[1]=quote(1,'1.60','1.64');p.pop(2)
        self.assertEqual(replay(entry(),p)['variant']['status'],'missing_quote')

    def test_gap_invalidates_only_variant(self):
        r=replay(entry(),[q for n,q in enumerate(path()) if n not in (1,2)])
        self.assertEqual(r['control']['status'],'priced')
        self.assertEqual(r['variant']['status'],'missing_path')

    def test_cap_tie_uses_timer(self):
        p=path();p[90]=quote(90,'1.50','1.54')
        r=replay(entry(),p)
        self.assertEqual(r['variant']['reason'],'fixed_90m')

    def test_missing_exit_preserved(self):
        e=entry();e['status']='missing_exit'
        r=replay(e,path()[:-1])
        self.assertEqual(r['control']['status'],'missing_quote')
        self.assertEqual(r['variant']['status'],'missing_quote')

    def test_conflicting_duplicates_and_bad_entry_fail(self):
        with self.assertRaises(ValueError): replay(entry(),path()+[quote(1,'1.90')])
        with self.assertRaises(ValueError): replay(entry(),path()[1:])

    def test_wrong_contract_and_zero_size_cannot_trigger(self):
        p=path()+[quote(1,'1.5','1.6',contract='OTHER'),quote(1,'1.5','1.6',size='0')]
        self.assertEqual(replay(entry(),p)['variant']['reason'],'fixed_90m')

    def test_float_boundary_is_not_rounded_into_trigger(self):
        p=path();p[1]=quote(1,'1.600000000000001','1.64')
        self.assertEqual(replay(entry(),p)['variant']['reason'],'fixed_90m')

    def test_no_postdecision_path_gap_invalidates_priced_exit(self):
        p=path();p[1]=quote(1,'1.6','1.64');p[2]=quote(2,'1.5','1.54')
        p=[q for n,q in enumerate(p) if n<3 or n==91]
        self.assertEqual(replay(entry(),p)['variant']['status'],'priced')

    def test_control_mismatch_fails_closed(self):
        with self.assertRaises(ValueError): replay(entry('2.20'),path())


if __name__=='__main__': unittest.main()
