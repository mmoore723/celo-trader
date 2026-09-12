import copy
import unittest
from research.jobs.assess_two_leg_initial_loss import independently_verify, assess, account, verify_aggregate_arithmetic
from research.jobs.replay_two_leg_initial_loss import replay, compare, PROTOCOL
from research.tests.test_two_leg_initial_loss_replay import entry,path,quote


class InitialLossAssessmentTests(unittest.TestCase):
    def test_reconstructs_threshold_and_costs(self):
        p=path();p[1]=quote(1,'1.6','1.64');p[2]=quote(2,'1.5','1.54')
        independently_verify(replay(entry(),p),entry())

    def test_no_trigger_and_cap_tie(self):
        p=path();p[90]=quote(90,'1.5','1.6')
        independently_verify(replay(entry(),p),entry())

    def test_rejects_altered_outcome_or_snapshot(self):
        r=replay(entry(),path())
        for key,value in [('net','999'),('bid','1'),('reason','initial_loss_20pct')]:
            bad=copy.deepcopy(r);bad['variant'][key]=value
            with self.assertRaises(ValueError): independently_verify(bad,entry())
        r['snapshots'][1]['bid_size']='0'
        with self.assertRaises(ValueError): independently_verify(r,entry())

    def test_small_sample_cannot_pass(self):
        rows=[replay(entry(),path())]
        report=dict(protocol=PROTOCOL,complete=True,entries=1,rows=rows,coverage={'priced':1},summary=compare(rows))
        baseline=dict(complete=True,rows=[entry()])
        r=assess(report,baseline)
        self.assertFalse(r['gates']['paired_count'])
        self.assertEqual(r['verdict'],'does_not_pass_frozen_improvement_test')
        report['complete']=False
        with self.assertRaises(ValueError): assess(report,baseline)

    def test_cash_affordability_and_costs(self):
        rows=[replay(entry(),path())]
        self.assertEqual(account(rows,'control')['final_cash'],'5006.70')
        self.assertEqual(account(rows,'variant','100')['accepted'],0)
        self.assertEqual(account(rows,'variant','100')['skipped'][0]['reason'],'insufficient_cash')

    def test_missing_path_is_not_zero_profit(self):
        p=[q for n,q in enumerate(path()) if n not in (1,2)]
        r=replay(entry(),p)
        independently_verify(r,entry())
        self.assertEqual(account([r],'variant')['accepted'],0)
        self.assertEqual(compare([r])['unpaired'],1)

    def test_liquidation_drawdown_tracks_held_path_only(self):
        p=path();p[1]=quote(1,'1.6','1.64');p[2]=quote(2,'1.5','1.54');p[3]=quote(3,'.1','.14')
        r=replay(entry(),p)
        self.assertEqual(account([r],'variant')['sampled_liquidation_drawdown'],'53.30')
        self.assertEqual(account([r],'control')['sampled_liquidation_drawdown'],'193.30')

    def test_independent_aggregate_rejects_bad_pf(self):
        rows=[replay(entry(),path())]
        summary=compare(rows);summary['control']['pf']='2'
        with self.assertRaises(ValueError):verify_aggregate_arithmetic(rows,summary)
