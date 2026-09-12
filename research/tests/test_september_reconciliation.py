"""Offline account reconciliation tests; not an application release."""
import copy
import unittest

from research.jobs.reconcile_september_paper_audit import reconcile

SID = 'V2_SPY_TREND_CONT'

def row(id=1, pnl=-30, entry=5.4, exit=5.25, qty=2, parent=None, status='closed'):
    return dict(id=id,parent_trade_id=parent,paper=1,ticker='SPY',contract_symbol='FIXTURE',
                strategy_id=SID,candidate_id='one',entry_time='2026-09-11T15:10:00-04:00',
                exit_time='2026-09-11T15:40:00-04:00',status=status,
                realized_pnl=pnl,entry_price=entry,exit_price=exit,contracts=qty)

def payload(rows=None):
    return dict(scope=dict(mode='paper',start='2026-09-08',end_exclusive='2026-09-12',strategies=[SID]),
        trades=rows if rows is not None else [row()], candidates=[dict(candidate_id='one',strategy_id=SID,
            ticker='SPY',metadata={'strategy_version':'2.1.0'})])

class ReconciliationTests(unittest.TestCase):
    def report(self,data=None):
        return reconcile(data or payload(),{SID:'2.1.0'})

    def test_recorded_arithmetic_and_explicit_cost_scenario(self):
        result = self.report()
        self.assertTrue(result['record_arithmetic_clean'])
        self.assertEqual('-30.00',result['finite_recorded_closed_leg_pnl'])
        self.assertEqual('-32.60',result['strategies'][SID]['current']['cost_scenario']['pnl'])
        self.assertFalse(result['cost_scenario_is_actual_fees'])

    def test_partial_closes_count_once_with_all_contracts(self):
        result=self.report(payload([row(qty=1,pnl=-15),row(id=2,qty=1,pnl=20,exit=5.6,parent=1)]))
        value=result['strategies'][SID]['current']
        self.assertEqual(1,value['completed_positions'])
        self.assertEqual('5.00',value['gross']['pnl'])
        self.assertEqual(1,value['gross']['wins'])
        self.assertEqual('2.40',value['cost_scenario']['pnl'])

    def test_open_parent_does_not_turn_partial_win_into_closed_position(self):
        result=self.report(payload([row(status='open',pnl=None),row(id=2,qty=1,pnl=20,exit=5.6,parent=1)]))
        self.assertEqual(0,result['strategies'][SID]['current']['completed_positions'])
        self.assertEqual('20.00',result['finite_recorded_closed_leg_pnl'])
        self.assertEqual('still_open',result['incomplete_positions'][0]['reason'])

    def test_unidentified_version_keeps_success_in_history(self):
        data=payload([row(pnl=30,exit=5.55)])
        data['candidates']=[]
        result=self.report(data)['strategies'][SID]
        self.assertEqual(1,result['all_versions']['gross']['wins'])
        self.assertEqual(0,result['current']['completed_positions'])
        self.assertEqual(1,result['other_or_unidentified_positions'])

    def test_incorrect_pnl_exposed_not_silently_qualified(self):
        result=self.report(payload([row(pnl=30)]))
        self.assertFalse(result['record_arithmetic_clean'])
        self.assertEqual('30.00',result['finite_recorded_closed_leg_pnl'])
        self.assertEqual('-30.00',result['leg_checks'][0]['recomputed_pnl'])
        self.assertEqual(0,result['strategies'][SID]['current']['completed_positions'])

    def test_duplicates_scope_and_candidate_mismatch_rejected(self):
        cases=[payload([row(),row()]), payload(), payload()]
        cases[1]['trades'][0]['entry_time']='2026-09-12T15:10:00-04:00'
        cases[2]['candidates'][0]['ticker']='TSLA'
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):
                self.report(case)

    def test_missing_parent_and_bad_price_are_not_zero_results(self):
        result=self.report(payload([row(parent=999),row(id=2,entry=None)]))
        self.assertEqual(2,len(result['incomplete_positions']))
        self.assertEqual(1,len(result['issues']))

    def test_nonfinite_is_rejected_and_inputs_unchanged(self):
        data=payload([row(pnl='NaN')])
        before=copy.deepcopy(data)
        result=self.report(data)
        self.assertFalse(result['record_arithmetic_clean'])
        self.assertEqual(before,data)

if __name__ == '__main__':
    unittest.main()
