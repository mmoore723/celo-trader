"""Local audit evidence tests; not part of an application release."""
import copy
import unittest
from research.jobs.verify_september_execution import verify_execution, recorded_quantity_account_scenario


def fixture():
    t = dict(id=1, parent_trade_id=None, status='closed', strategy_id='s',
             contract_symbol='contract', contracts=2, entry_price='8.50', exit_price='7.35',
             entry_time='2026-09-11T10:00:00-04:00', exit_time='2026-09-11T11:30:00-04:00',
             entry_order_id='entry', exit_order_id='exit')
    events = []
    for side, prefix in [('buy', 'entry'), ('sell', 'exit')]:
        base = dict(linked_trade_id=1, side=side, strategy_id='s', contract_symbol='contract',
                    filled_qty=2, fill_price=t[prefix + '_price'], status='filled')
        events.append(dict(base, id=len(events), order_id=t[prefix+'_order_id'], event_type='filled'))
        events.append(dict(base, id=len(events), order_id=None, event_type='execution_summary'))
    return dict(trades=[t], broker_events=events)


class ExecutionEvidenceTests(unittest.TestCase):
    def test_summary_uses_trade_link_not_missing_order_id(self):
        self.assertEqual(verify_execution(fixture())['verified_entry_or_exit_sides'], 2)

    def test_repeated_events_not_trades(self):
        p=fixture(); p['broker_events'].append(copy.deepcopy(p['broker_events'][0]))
        self.assertEqual(verify_execution(p)['unique_events'], 4)
        self.assertEqual(verify_execution(p)['verified_entry_or_exit_sides'], 2)

    def test_conflicting_duplicate_fails(self):
        p=fixture(); e=copy.deepcopy(p['broker_events'][0]); e['fill_price']='9'
        p['broker_events'].append(e)
        with self.assertRaises(ValueError): verify_execution(p)

    def test_bad_price_quantity_side_identity_detected(self):
        for key, value in [('fill_price','9'),('filled_qty',1),('side','sell'),
                           ('contract_symbol','other'),('strategy_id','other')]:
            p=fixture(); p['broker_events'][0][key]=value
            self.assertTrue(verify_execution(p)['issues'], key)

    def test_missing_summary_not_verified(self):
        p=fixture(); p['broker_events'].pop()
        self.assertEqual(verify_execution(p)['verified_entry_or_exit_sides'], 1)

    def test_broker_fill_can_omit_strategy_but_summary_cannot(self):
        p=fixture(); p['broker_events'][0]['strategy_id']=None
        self.assertEqual(verify_execution(p)['verified_entry_or_exit_sides'], 2)
        p['broker_events'][1]['strategy_id']=None
        self.assertEqual(verify_execution(p)['verified_entry_or_exit_sides'], 1)

    def test_account_costs_and_notional(self):
        r=recorded_quantity_account_scenario(fixture())
        self.assertEqual(r['final_cash'],'4767.40')
        self.assertEqual(r['maximum_concurrent_premium'],'1700.00')
        self.assertEqual(r['closed_pnl_peak_to_trough'],'232.60')

    def test_cash_shortfall_not_hidden(self):
        self.assertEqual(recorded_quantity_account_scenario(fixture(),initial='1000')['insufficient_cash_trade_ids'],[1])

    def test_partial_position_rejected(self):
        p=fixture(); p['trades'][0]['parent_trade_id']=3
        with self.assertRaises(ValueError): recorded_quantity_account_scenario(p)
