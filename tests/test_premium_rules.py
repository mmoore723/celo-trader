import unittest
from datetime import datetime, timedelta, timezone
from strategy_health.premium_rules import advance, replay, net, valid_quote, RULES, giveback_arm_dollars
from strategy_health.premium_research import assess, initialize
import sqlite3

T = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)

def quote(bid, second=1, size=10):
    stamp=(T+timedelta(seconds=second)).timestamp()*1000
    return dict(symbol='TEST',bid=bid,ask=bid+.02,bidsize=size,asksize=10,bid_date=stamp,ask_date=stamp)

class PremiumRulesTest(unittest.TestCase):
    def step(self, rule, state, bid, second=1, qty=1):
        return advance(rule,state,entry=1.,quantity=qty,quote=quote(bid,second),
                       received=T+timedelta(seconds=second),symbol='TEST')

    def test_exact_targets_and_independence(self):
        for pct in (2,5,15,20,25):
            rule,target=f'premium_{pct}pct',1+pct/100
            self.assertNotIn('signal',self.step(rule,{},target-.001))
            self.assertIn('signal',self.step(rule,{},target))

    def test_giveback_arms_only_above_costs(self):
        state=self.step('giveback_25pct',{},1.02)
        self.assertFalse(state['armed'])
        self.assertNotIn('signal',self.step('giveback_25pct',state,1.,2))
        state=self.step('giveback_25pct',{},1.20)
        self.assertNotIn('signal',self.step('giveback_25pct',state,1.151,2))
        self.assertIn('signal',self.step('giveback_25pct',state,1.15,2))

    def test_eight_hypotheses_no_five_percent_giveback(self):
        self.assertEqual(len(RULES),8)
        self.assertNotIn('giveback_5pct',RULES)
        self.assertAlmostEqual(float(giveback_arm_dollars('giveback_15pct')),3.30/.85)
        self.assertAlmostEqual(float(giveback_arm_dollars('giveback_20pct')),4.125)
        self.assertAlmostEqual(float(giveback_arm_dollars('giveback_25pct')),4.40)

    def test_arming_boundary_and_gap_below_cost_floor(self):
        self.assertFalse(self.step('giveback_25pct',{},1.043999)['armed'])
        state=self.step('giveback_25pct',{},1.044)
        self.assertTrue(state['armed'])
        self.assertNotIn('signal',self.step('giveback_25pct',state,1.02,2))
        hit=self.step('giveback_25pct',state,1.033,2)
        self.assertIn('signal',hit)
        self.assertEqual(net(1.,1.033),0)

    def test_next_bid_cannot_book_giveback_loss(self):
        rows=[dict(received_at=T+timedelta(seconds=s),quote=quote(b,s))
              for s,b in [(1,1.20),(2,1.15),(3,1.02),(4,1.04)]]
        result=replay('giveback_25pct',rows,entry=1.,entry_at=T,
                      end=T+timedelta(seconds=5),symbol='TEST',quantity=3)
        self.assertEqual(result['exit']['bid'],1.04)
        self.assertGreaterEqual(result['net_pnl'],0)

    def test_observed_unfilled_floor_keeps_baseline_not_exclusion(self):
        rows=[dict(received_at=T+timedelta(seconds=s),quote=quote(b,s))
              for s,b in [(1,1.20),(2,1.15),(3,1.02),(4,1.01)]]
        result=replay('giveback_25pct',rows,entry=1.,entry_at=T,
                      end=T+timedelta(seconds=5),symbol='TEST')
        self.assertEqual(result['status'],'baseline')
        self.assertTrue(result['unfilled_giveback_floor'])

    def test_all_givebacks_respect_cost_floor(self):
        for pct in (15,20,25):
            rule=f'giveback_{pct}pct'
            state=self.step(rule,{},1.10)
            self.assertTrue(state['armed'])
            self.assertNotIn('signal',self.step(rule,state,1.032,2))
            self.assertIn('signal',self.step(rule,state,1.033,2))

    def test_spec_records_exact_rules_and_research_only_flags(self):
        from strategy_health.premium_rules import rule_specifications
        specs=rule_specifications()
        self.assertEqual(specs['giveback_25pct']['arm_dollars_per_contract'],'4.4')
        self.assertEqual(specs['premium_20pct']['gain_fraction'],'0.2')
        self.assertTrue(specs['giveback_20pct']['research_only'])
        self.assertFalse(specs['giveback_25pct']['research_only'])

    def test_comparisons_use_common_cohort(self):
        from strategy_health.premium_research import compare
        from unittest.mock import Mock, patch
        sample=dict(candidate_id='1',observed_at=T.isoformat(),entry_contract='TEST',entry_ask=1)
        control=dict(id='1',entry_at=T.isoformat(),exit_at=(T+timedelta(seconds=5)).isoformat(),pnl=-10)
        reader=Mock();reader.observations.return_value=[]
        def result(rule,*args,**kwargs):
            return dict(status='missing_next_quote' if rule=='premium_2pct' else 'baseline',max_gap_seconds=0)
        with sqlite3.connect(':memory:') as conn, patch('strategy_health.premium_research.replay',side_effect=result):
            report=compare(conn,reader,samples=[sample],completed=[control],account='A',mode='paper',strategy='TEST',ticker='QQQ',version='1')
            self.assertEqual(len(report['candidates']),8)
            for c in report['candidates']:
                self.assertEqual(c['tested_exits'],8)
                self.assertEqual(c['selection']['paired_trades'],0)
                self.assertFalse(c['promotion_ready'])

    def test_confidence_uses_actual_candidate_count(self):
        result=assess([],0)
        self.assertEqual(result['tested_exits'],8)
        self.assertAlmostEqual(result['confidence'],.99375)
        self.assertAlmostEqual(assess([],0,tested_exits=3)['confidence'],1-.05/3)
        with self.assertRaises(ValueError): assess([],0,tested_exits=0)

    def test_partial_close_does_not_create_giveback(self):
        state=self.step('giveback_25pct',{},1.20,qty=8)
        self.assertNotIn('signal',self.step('giveback_25pct',state,1.20,2,qty=3))

    def test_recovery_and_duplicate_quote(self):
        import json
        state=json.loads(json.dumps(self.step('giveback_25pct',{},1.20)))
        self.assertEqual(state,self.step('giveback_25pct',state,1.10))
        result=self.step('giveback_25pct',state,1.15,2)
        self.assertIn('signal',result)
        self.assertEqual(result,self.step('giveback_25pct',result,1.30,3))

    def test_bad_quotes_rejected(self):
        for changes in [dict(bid=2,ask=1),dict(bidsize=0),dict(asksize=None),
                        dict(bid=float('nan')),dict(symbol='WRONG'),dict(bid_date=0),
                        dict(bid_date=(T+timedelta(seconds=20)).timestamp()*1000)]:
            q=quote(1.30);q.update(changes)
            self.assertIsNone(valid_quote(q,T+timedelta(seconds=1),1,'TEST'))

    def test_replay_uses_subsequent_bid_not_trigger(self):
        observations=[dict(received_at=T+timedelta(seconds=s),quote=quote(b,s))
                      for s,b in [(1,1.02),(2,1.01)]]
        result=replay('premium_2pct',observations,entry=1.,entry_at=T,
                      end=T+timedelta(seconds=5),symbol='TEST',quantity=3)
        self.assertEqual(result['status'],'hypothetical')
        self.assertEqual(result['exit']['bid'],1.01)
        self.assertEqual(result['net_pnl'],net(1.,1.01,3))
        self.assertLess(result['net_pnl'],0)  # Gross target does not promise net profit.

    def test_missing_next_quote_is_not_a_fill(self):
        result=replay('premium_2pct',[dict(received_at=T+timedelta(seconds=1),quote=quote(1.02))],
                      entry=1.,entry_at=T,end=T+timedelta(seconds=5),symbol='TEST')
        self.assertEqual(result['status'],'missing_next_quote')

    def test_costs_quantity_and_spread(self):
        self.assertAlmostEqual(net(2,2.5,4),186.8)

    def test_insufficient_evidence_cannot_pass(self):
        self.assertFalse(assess([],0)['evidence_passed'])
        rows=[dict(id=str(i),entry_at=(T+timedelta(days=i)).isoformat(),
                   exit_at=(T+timedelta(days=i,minutes=5)).isoformat(),
                   baseline_net=1,candidate_net=5) for i in range(20)]
        self.assertFalse(assess(rows,20)['evidence_passed'])
        self.assertFalse(assess(rows*3,100)['gates']['coverage'])

    def test_schema_restart_preserves_frozen_spec(self):
        with sqlite3.connect(':memory:') as conn:
            first=initialize(conn)
            self.assertEqual(first,initialize(conn))
            conn.execute("UPDATE premium_exit_specs SET specification='changed'")
            with self.assertRaises(ValueError): initialize(conn)
