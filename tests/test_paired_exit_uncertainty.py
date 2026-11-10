from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import unittest
from strategy_health.paired_exit_accounting import Scope
from strategy_health.paired_exit_uncertainty import analyze_bucket


class PairedUncertaintyTests(unittest.TestCase):
    def row(self,day,delta=2,status='evaluable',suffix=''):
        at=datetime(2026,11,1,15,tzinfo=timezone.utc)+timedelta(days=day)
        return dict(scope=Scope('account','paper','strategy','SPY','v1','experiment'),
            trade_id=str(day)+suffix,entry_at=at,session=at.date().isoformat(),
            baseline_policy='base',candidate_policy='candidate',pricing_identity=('cost-v1',),
            status=status,baseline={'net':D(10),'closed_at':at+timedelta(minutes=30)},
            candidate={'net':D(10)+D(delta),'closed_at':at+timedelta(minutes=10)},
            improvement=D(delta),baseline_winner_to_loss=D(delta)<-10)

    def analyze(self,rows,**changes):
        config=dict(confidence=.95,family_size=14,resamples=10000,seed=20261109,holdout_fraction=.3)
        config.update(changes)
        return analyze_bucket(rows,**config)

    def test_exact_constant_and_chronological_split(self):
        result=self.analyze([self.row(i) for i in range(10)])
        self.assertEqual(7,result['development']['paired_trades'])
        self.assertEqual(3,result['holdout']['paired_trades'])
        self.assertEqual(2,result['uncertainty']['adjusted_one_sided_lower_bound'])
        self.assertEqual('INSUFFICIENT EVIDENCE',result['recommendation'])

    def test_blocked_sessions_determine_split_and_remain_counted(self):
        rows=[self.row(i,status='blocked' if i>=7 else 'evaluable') for i in range(10)]
        result=self.analyze(rows)
        self.assertEqual(3,result['holdout']['attempts'])
        self.assertEqual(0,result['holdout']['paired_trades'])
        self.assertIsNone(result['holdout']['mean_improvement'])
        self.assertEqual(.7,result['all']['coverage'])

    def test_trade_weighted_not_session_weighted(self):
        rows=[self.row(0,0,suffix=str(i)) for i in range(9)]+[self.row(1,100)]
        result=self.analyze(rows)
        self.assertEqual(D(10),result['all']['mean_improvement'])
        self.assertEqual(D(0),result['all']['median_improvement'])

    def test_seed_reproducibility_and_multiple_comparison_penalty(self):
        rows=[self.row(i,i-3) for i in range(20)]
        one=self.analyze(rows,family_size=1)
        many=self.analyze(rows)
        self.assertEqual(many,self.analyze(rows))
        self.assertLessEqual(many['uncertainty']['adjusted_one_sided_lower_bound'],
                             one['uncertainty']['adjusted_one_sided_lower_bound'])

    def test_sparse_data_does_not_manufacture_uncertainty(self):
        self.assertIsNone(self.analyze([self.row(0)])['uncertainty'])
        self.assertIsNone(self.analyze([self.row(0,status='blocked')])['uncertainty'])

    def test_no_pooling_or_duplicate_evidence(self):
        row=self.row(0)
        for rows in ([row,row],[row,dict(self.row(1),pricing_identity=('other',))],
                     [row,dict(self.row(1),candidate_policy='other')],[]):
            with self.assertRaises(ValueError): self.analyze(rows)

    def test_inconsistent_dates_or_math_rejected(self):
        for changes in ({'session':'2020-01-01'},{'improvement':D(999)},
                        {'entry_at':datetime(2026,11,1)},{'status':'unknown'}):
            with self.assertRaises(ValueError): self.analyze([dict(self.row(0),**changes)])

    def test_invalid_parameters_rejected(self):
        for changes in ({'family_size':0},{'resamples':0},{'seed':-1},{'confidence':1},
                        {'holdout_fraction':0},{'confidence':float('nan')},{'family_size':True}):
            with self.assertRaises(ValueError):self.analyze([self.row(0)],**changes)
