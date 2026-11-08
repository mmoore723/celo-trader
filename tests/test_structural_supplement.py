from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import unittest
from strategy_health.paired_exit_accounting import Entry,Scope,Intent,Quote,Pricing,compare
from strategy_health.structural_supplement import StockPrint,EntryLevel,StructuralSpec,candidate_intents,level_from_context,evaluate_pair

T=datetime(2026,11,9,15,tzinfo=timezone.utc)
def at(n): return T+timedelta(seconds=n)


class StructuralSupplementTests(unittest.TestCase):
    def setUp(self):
        self.entry=Entry(Scope('a','paper','native','SPY','v1','experiment'),'1','contract',T,D(2),4,D(1),'entry-fill')
        self.level=EntryLevel(self.entry.scope,'1','or_low',D(99),at(-60),at(-1),'level-evidence')
        self.spec=StructuralSpec('or_low','call','tradier',5,10,'spec-hash')
        self.native=[Intent(at(20),4,'native_timer','native-event')]
        self.fills=[self.fill(self.native[0],21)]
        self.prices=[self.p(n,100) for n in (5,10,15,20,21)]

    def p(self,n,price):return StockPrint('SPY',D(price),at(n),at(n),'source-'+str(n),'receipt-'+str(n),'tradier','forward_observed')
    def fill(self,intent,n):return dict(at=at(n),quantity=intent.contracts,intent_evidence=intent.evidence_id,reason=intent.reason,quote_evidence='q'+str(n))
    def run_candidate(self,**kw):
        args=dict(entry=self.entry,native_intents=self.native,native_fills=self.fills,level=self.level,
                  entry_stock=self.p(0,100),prints=self.prices,spec=self.spec)
        args.update(kw);return candidate_intents(**args)

    def test_call_breach_exits_remaining_at_receipt_not_candle_close(self):
        r=self.run_candidate(prints=[self.p(5,100),self.p(10,98),*self.prices[2:]])
        self.assertEqual('ready_for_pricing',r['status'])
        self.assertEqual([Intent(at(10),4,'structural_adverse_breach','receipt-10')],r['intents'])

    def test_put_mirror_and_equality_holds(self):
        r=self.run_candidate(level=replace(self.level,value=D(101)),spec=replace(self.spec,option_type='put'),
            prints=[self.p(5,101),self.p(10,102),*self.prices[2:]])
        self.assertEqual(at(10),r['trigger_at'])
        self.assertEqual('native_unchanged_no_observed_breach',self.run_candidate(prints=[self.p(n,99) for n in (5,10,15,20,21)])['action'])

    def test_native_target_or_safety_exit_is_not_delayed(self):
        native=[Intent(at(5),4,'mandatory_safety','safety')]
        r=self.run_candidate(native_intents=native,native_fills=[self.fill(native[0],21)],prints=[self.p(n,98) for n in (5,10,15,20,21)])
        self.assertEqual(native,r['intents']);self.assertEqual('native_full_exit_already_triggered',r['action'])

    def test_partial_completed_before_breach_preserved(self):
        native=[Intent(at(5),2,'native_partial','p'),Intent(at(20),2,'native_timer','f')]
        r=self.run_candidate(native_intents=native,native_fills=[self.fill(native[0],6),self.fill(native[1],21)],
            prints=[self.p(5,100),self.p(10,98),*self.prices[2:]])
        self.assertEqual(native[0],r['intents'][0]);self.assertEqual(2,r['intents'][1].contracts)

    def test_pending_partial_not_invented_as_filled_or_cancelled(self):
        native=[Intent(at(5),2,'native_partial','p'),Intent(at(20),2,'native_timer','f')]
        r=self.run_candidate(native_intents=native,native_fills=[self.fill(native[0],10),self.fill(native[1],21)],
            prints=[self.p(5,100),self.p(10,98),*self.prices[2:]])
        self.assertIn('breach_overlaps_native_partial_execution',r['errors'])

    def test_missing_late_unclosed_or_wrong_side_levels_block(self):
        variants=[None,replace(self.level,recorded_at=at(1)),replace(self.level,source_completed_at=at(1)),
                  replace(self.level,value=D(100)),replace(self.level,value=D('NaN'))]
        for level in variants:
            with self.subTest(level=level):self.assertEqual('blocked',self.run_candidate(level=level)['status'])

    def test_exact_field_only_never_atr_fallback(self):
        with self.assertRaisesRegex(ValueError,'missing_entry_level'):
            level_from_context(self.entry,{'atr_stop':98},'or_low',source_completed_at=at(-60),recorded_at=at(-1),evidence_id='e')
        got=level_from_context(self.entry,{'structural_levels':{'support':99}},'structural_levels.support',
            source_completed_at=at(-60),recorded_at=at(-1),evidence_id='e')
        self.assertEqual(D(99),got.value)

    def test_scope_and_field_mismatch_block(self):
        for level in [replace(self.level,scope=replace(self.entry.scope,mode='live')),
                      replace(self.level,trade_id='2'),replace(self.level,field='other')]:
            self.assertEqual('blocked',self.run_candidate(level=level)['status'])

    def test_recovered_stale_future_prints_rejected_without_false_breach(self):
        bad=[replace(self.p(7,98),provenance='history_recovered'),replace(self.p(8,98),source_at=at(0)),
             replace(self.p(9,98),source_at=at(10))]
        r=self.run_candidate(prints=self.prices+bad)
        self.assertEqual('native_unchanged_no_observed_breach',r['action'])
        self.assertEqual({'not_forward_observed':1,'stale_or_future_source':2},r['rejected_prints'])

    def test_gaps_through_later_native_exit_block_even_if_candidate_triggered(self):
        r=self.run_candidate(prints=[self.p(5,98),self.p(21,100)])
        self.assertIn('underlying_gap_through_native_exit',r['errors'])
        self.assertEqual('blocked',self.run_candidate(prints=[])['status'])

    def test_duplicate_source_events_not_new_observations(self):
        p=self.p(5,100)
        r=self.run_candidate(prints=self.prices+[p,replace(p,received_at=at(6),evidence_id='repeat')])
        self.assertEqual(5,r['underlying_observations'])
        r=self.run_candidate(prints=self.prices+[replace(p,price=D(98),evidence_id='conflict')])
        self.assertIn('conflicting_stock_source_event',r['errors'])

    def test_entry_stock_must_be_known_and_current(self):
        for p in [self.p(1,100),self.p(-6,100),replace(self.p(0,100),ticker='QQQ')]:
            self.assertEqual('blocked',self.run_candidate(entry_stock=p)['status'])

    def test_no_native_quantity_invention(self):
        self.assertEqual('blocked',self.run_candidate(native_fills=[])['status'])
        bad=[dict(self.fills[0],quantity=3)]
        self.assertIn('invalid_native_fill_mapping',self.run_candidate(native_fills=bad)['errors'])

    def test_integration_prices_same_contract_both_branches(self):
        result=self.run_candidate(prints=[self.p(5,100),self.p(10,98),*self.prices[2:]])
        quotes=[Quote('contract',at(n),at(n),at(n),D(price),D(price)+D('.1'),5,'q'+str(n))
                for n,price in [(5,'2'),(10,'1.5'),(15,'2'),(20,'3'),(21,'3')]]
        pair=compare(self.entry,self.native,result['intents'],quotes,Pricing(5,5,10,D('.01'),D('.5'),'fees'),
                     baseline_policy='native',candidate_policy='structure')
        self.assertEqual('evaluable',pair['status'])
        self.assertEqual(D(-600),pair['improvement']);self.assertTrue(pair['baseline_winner_to_loss'])

    def test_orchestrator_uses_priced_native_fills_not_an_assumed_fill_clock(self):
        native=[Intent(at(5),2,'partial','p'),Intent(at(20),2,'native_timer','f')]
        quotes=[Quote('contract',at(n),at(n),at(n),D(2),D('2.1'),5,'q'+str(n)) for n in (10,15,20)]
        # The partial request at5cannot fill before the first quote at10.
        result=evaluate_pair(self.entry,native,self.level,self.p(0,100),
            [self.p(5,100),self.p(8,98),self.p(15,100),self.p(20,100)],self.spec,quotes,
            Pricing(5,5,10,D('.01'),D('.5'),'fees'),baseline_policy='native',candidate_policy='candidate')
        self.assertEqual('blocked',result['status'])
        self.assertIn('breach_overlaps_native_partial_execution',result['errors'])

    def test_option_and_structure_failure_stages_are_distinct(self):
        args=(self.entry,self.native,None,self.p(0,100),self.prices,self.spec)
        pricing=Pricing(5,5,10,D('.01'),D('.5'),'fees')
        result=evaluate_pair(*args,[],pricing,baseline_policy='native',candidate_policy='candidate')
        self.assertEqual('native_option_pricing',result['input_stage'])
        quotes=[Quote('contract',at(n),at(n),at(n),D(2),D('2.1'),5,'q'+str(n)) for n in (5,10,15,20)]
        result=evaluate_pair(*args,quotes,pricing,baseline_policy='native',candidate_policy='candidate')
        self.assertEqual('structural_inputs',result['input_stage'])
        self.assertIn('missing_entry_level',result['errors'])


if __name__=='__main__':unittest.main()
