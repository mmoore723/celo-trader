from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import unittest
from strategy_health.paired_exit_accounting import Scope,Entry,Intent,Quote,Pricing,compare,summarize

T=datetime(2026,11,9,15,tzinfo=timezone.utc)


class PairedExitTests(unittest.TestCase):
    def setUp(self):
        self.entry=Entry(Scope('a','paper','strategy','SPY','v1','experiment-v1'),'trade-1','contract',T,D(2),2,D(1),'entry-fill')
        self.config=Pricing(5,5,10,D('.01'),D('.5'),'fees-v1')
        self.base=[Intent(T+timedelta(seconds=10),2,'native','baseline-event')]
        self.candidate=[Intent(T+timedelta(seconds=5),2,'structure','candidate-event')]
        self.quotes=[self.q(5,'2.5'),self.q(10,'2.8')]

    def q(self,seconds,bid):
        at=T+timedelta(seconds=seconds)
        return Quote('contract',at,at,at,D(bid),D(bid)+D('.1'),5,'q'+str(seconds))

    def run_pair(self,**changes):
        args=dict(entry=self.entry,baseline=self.base,candidate=self.candidate,quotes=self.quotes,
                  pricing=self.config,baseline_policy='native-v1',candidate_policy='candidate-v1')
        args.update(changes);return compare(**args)

    def test_same_cost_model_and_actual_entry(self):
        r=self.run_pair();self.assertEqual('evaluable',r['status'])
        self.assertEqual(D(156),r['baseline']['net']);self.assertEqual(D(96),r['candidate']['net'])
        self.assertEqual(D(-60),r['improvement']);self.assertEqual('hypothetical shadow',r['result_kind'])

    def test_partial_exit_conserves_quantity_and_fees(self):
        base=[replace(self.candidate[0],contracts=1),replace(self.base[0],contracts=1)]
        r=self.run_pair(baseline=base)
        self.assertEqual(D(126),r['baseline']['net']);self.assertEqual(D(-30),r['improvement'])

    def test_baseline_winner_to_loss(self):
        r=self.run_pair(quotes=[self.q(5,'1.9'),self.q(10,'2.8')])
        self.assertTrue(r['baseline_winner_to_loss'])
        self.assertEqual(1,summarize([r])[0]['baseline_winners_turned_losses'])

    def test_no_late_quote_or_carried_price(self):
        r=self.run_pair(quotes=[self.q(0,'2.5'),self.q(16,'2.8')])
        self.assertEqual('blocked',r['status']);self.assertIn('baseline:unavailable_eligible_exit_quote',r['errors'])

    def test_size_and_source_age_enforced(self):
        for field,value in [('bid_size',1),('bid_at',T-timedelta(seconds=20)),('ask_at',T+timedelta(days=1))]:
            with self.subTest(field=field):
                self.assertEqual('blocked',self.run_pair(quotes=[replace(q,**{field:value}) for q in self.quotes])['status'])

    def test_gap_through_later_exit_blocks_even_when_both_exits_priced(self):
        base=[replace(self.base[0],at=T+timedelta(seconds=60))]
        r=self.run_pair(baseline=base,quotes=[self.q(5,'2.5'),self.q(60,'2.8')])
        self.assertEqual('blocked',r['status']);self.assertIn('quote_receipt_gap_through_later_exit',r['errors'])
        report=summarize([r])[0];self.assertEqual(0,report['evaluable']);self.assertIsNone(report['baseline']['net'])

    def test_duplicate_quotes_deduplicated_conflicts_rejected(self):
        self.assertEqual('evaluable',self.run_pair(quotes=self.quotes+self.quotes)['status'])
        r=self.run_pair(quotes=self.quotes+[replace(self.quotes[0],bid=D(99))])
        self.assertIn('conflicting_duplicate_quote',r['errors'])

    def test_wrong_contract_and_naive_clock_rejected(self):
        self.assertIn('quote_contract_mismatch',self.run_pair(quotes=[replace(self.quotes[0],contract='other')])['errors'])
        self.assertIn('aware_timestamp_required',self.run_pair(entry=replace(self.entry,filled_at=T.replace(tzinfo=None)))['errors'])

    def test_no_unfinished_or_oversized_exit(self):
        for qty in (1,3):
            self.assertEqual('blocked',self.run_pair(candidate=[replace(self.candidate[0],contracts=qty)])['status'])

    def test_scope_and_policy_isolation(self):
        rows=[self.run_pair()]
        for field,value in [('account','b'),('mode','live'),('version','v2'),('ticker','QQQ'),('strategy','other')]:
            rows.append(self.run_pair(entry=replace(self.entry,scope=replace(self.entry.scope,**{field:value}))))
        rows.append(self.run_pair(candidate_policy='candidate-v2'))
        self.assertEqual(7,len(summarize(rows)))
        self.assertTrue(all(r['recommendation']=='INSUFFICIENT EVIDENCE' for r in summarize(rows)))

    def test_duplicate_attempt_never_inflates_sample(self):
        r=self.run_pair()
        with self.assertRaisesRegex(ValueError,'duplicate_paired_attempt'):summarize([r,r])

    def test_missing_fees_and_nonfinite_prices_block(self):
        self.assertEqual('blocked',self.run_pair(pricing=replace(self.config,fee_schedule_version=''))['status'])
        self.assertEqual('blocked',self.run_pair(entry=replace(self.entry,premium=D('NaN')))['status'])

    def test_no_winning_claim_from_empty_summary(self):
        r=self.run_pair(quotes=[]);s=summarize([r])[0]
        self.assertIsNone(s['baseline']['win_rate']);self.assertIsNone(s['paired_mean_improvement'])
        self.assertEqual('INSUFFICIENT EVIDENCE',s['recommendation'])

    def test_stale_receipts_cannot_fill_coverage_gap(self):
        base=[replace(self.base[0],at=T+timedelta(seconds=30))]
        quotes=[self.q(5,'2.5'),self.q(30,'2.8')]
        quotes += [replace(self.q(s,'2.7'),bid_at=T,ask_at=T) for s in (10,15,20,25)]
        r=self.run_pair(baseline=base,quotes=quotes)
        self.assertIn('quote_receipt_gap_through_later_exit',r['errors'])

    def test_bad_quote_skipped_for_later_valid_quote(self):
        quotes=[replace(self.q(5,'2.5'),bid=D('NaN')),self.q(6,'2.5'),self.q(10,'2.8')]
        r=self.run_pair(quotes=quotes)
        self.assertEqual('evaluable',r['status'])
        self.assertEqual('q6',r['candidate']['fills'][0]['quote_evidence'])


if __name__=='__main__':unittest.main()
