from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import unittest
from strategy_health.paired_exit_accounting import Entry,Scope
from strategy_health.native_exit_requests import context_hash,observed_intents

T=datetime(2026,11,9,15,tzinfo=timezone.utc)


class NativeRequestTests(unittest.TestCase):
    def setUp(self):
        self.context={'strategy_version':'v1','selected_test_policy':{'exit_minutes':120}}
        self.entry=Entry(Scope('a','paper','strategy','AMZN','v1','e1'),'1','contract',T,Decimal(2),4,Decimal(0),'fill')

    def event(self,n,qty=4,remaining=4,reason='selected_test_120m'):
        return {'event_id':str(n),'cycle_id':str(n),'stage':'exit_order_request',
            'recorded_at':(T+timedelta(seconds=n)).isoformat(),'mode':'paper',
            'evidence_type':'native_decision_observation_not_fill',
            'trade':{'id':1,'broker_account_id':'a','strategy_id':'strategy','ticker':'AMZN',
                'contract_symbol':'contract','strategy_context_json':self.context},
            'snapshot':{'complete':True,'issues':[],'data':{'action_id':str(n),'remaining_contracts':remaining,
                'order':{'symbol':'contract','qty':qty,'side':'sell','position_intent':'sell_to_close',
                    'order_context':{'exit_reason':reason}}}}}

    def run_events(self,events,entry=None):
        return observed_intents(entry or self.entry,events,frozen_context_hash=context_hash(self.context))

    def test_full_exit_keeps_native_reason_and_time_without_timer_substitution(self):
        r=self.run_events([self.event(8)])
        self.assertEqual('selected_test_120m',r['intents'][0].reason)
        self.assertEqual(T+timedelta(seconds=8),r['intents'][0].at)
        self.assertFalse(r['decision_coverage_verified'])

    def test_partial_requests_retries_and_duplicate_records(self):
        first=self.event(1,2,4,'stage1_profit_take')
        r=self.run_events([first,first,self.event(2,2,4,'stage1_profit_take'),self.event(3,2,2,'native_stop')])
        self.assertEqual([2,2],[i.contracts for i in r['intents']])
        self.assertEqual(['2'],r['retry_request_ids'])

    def test_partial_fill_divergence_is_not_reconstructed(self):
        with self.assertRaisesRegex(ValueError,'quantity_divergence'):
            self.run_events([self.event(1,2,4,'stage1'),self.event(2,3,3,'native_stop')])

    def test_missing_quantity_and_truncated_snapshot_block(self):
        for field,value in [('complete',False),('issues',['snapshot_limit'])]:
            event=self.event(1);event['snapshot'][field]=value
            with self.assertRaisesRegex(ValueError,'incomplete_exit_request_snapshot'):self.run_events([event])
        with self.assertRaisesRegex(ValueError,'positive_integer_quantity'):self.run_events([self.event(1,None)])

    def test_scopes_cannot_mix(self):
        for field,value in [('mode','live'),('account','b'),('ticker','SPY'),('strategy','other'),('version','v2')]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.run_events([self.event(1)],replace(self.entry,scope=replace(self.entry.scope,**{field:value})))

    def test_policy_change_conflict_and_unfinished_position_block(self):
        event=self.event(1);event['trade']['strategy_context_json']={'strategy_version':'v1','selected_test_policy':{'exit_minutes':30}}
        with self.assertRaisesRegex(ValueError,'policy_context_changed'):self.run_events([event])
        first=self.event(1);other=self.event(2);other['snapshot']['data']['action_id']='1'
        with self.assertRaisesRegex(ValueError,'conflicting_request_identity'):self.run_events([first,other])
        with self.assertRaisesRegex(ValueError,'incomplete_native_exit_requests'):self.run_events([self.event(1,2,4,'partial')])

    def test_observed_native_requests_feed_paired_shadow_accounting(self):
        from strategy_health.paired_exit_accounting import Quote,Intent,Pricing,compare
        native=self.run_events([self.event(8)])
        quotes=[Quote('contract',T+timedelta(seconds=s),T+timedelta(seconds=s),T+timedelta(seconds=s),
                      Decimal(price),Decimal(price)+Decimal('.1'),5,str(s)) for s,price in [(5,'2.5'),(8,'3')]]
        result=compare(self.entry,native['intents'],[Intent(T+timedelta(seconds=5),4,'structure','candidate-event')],
            quotes,Pricing(5,5,10,Decimal('.01'),Decimal('.5'),'fees-v1'),baseline_policy='native-120',candidate_policy='candidate-v1')
        self.assertEqual('evaluable',result['status'])
        self.assertEqual(Decimal(-200),result['improvement'])
        self.assertEqual('hypothetical shadow',result['result_kind'])

    def test_event_identity_conflicts_block_and_later_requests_are_distinct_from_retries(self):
        first=self.event(1);second=self.event(2);second['event_id']='1'
        with self.assertRaisesRegex(ValueError,'conflicting_event_identity'):self.run_events([first,second])
        result=self.run_events([first,self.event(2,4,4,'different_later_reason')])
        self.assertEqual([],result['retry_request_ids'])
        self.assertEqual(['2'],result['requests_after_hypothetical_close'])


if __name__=='__main__':unittest.main()
