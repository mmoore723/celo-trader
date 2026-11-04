import unittest
from api.routes.learning_trade_practice import exercises


class TradePracticeTests(unittest.TestCase):
    def row(self, **changes):
        return dict(dict(id=1,parent_trade_id=None,strategy_context_json='{"strategy_version":"v1"}',
            metadata_json='{}',realized_pnl=-20,entry_price=2,exit_price=1.8,exit_time='2026-11-03T11:00:00',
            entry_time='2026-11-03T10:30:00',ticker='TSLA',option_type='call',contracts=1),**changes)

    def test_real_record_is_not_synthetic_or_claimed_broker_confirmed(self):
        items, excluded=exercises([self.row()], 'v1', 'paper')
        self.assertEqual('Loss',items[0]['answer'])
        self.assertFalse(items[0]['synthetic'])
        self.assertIn('confirmation incomplete',items[0]['source'])
        self.assertEqual({},excluded)

    def test_missing_conflicting_versions_and_invalid_prices_are_excluded(self):
        items,excluded=exercises([self.row(strategy_context_json='{}'),
            self.row(metadata_json='{"strategy_version":"v2"}'),self.row(exit_price=float('nan'))],'v1','paper')
        self.assertEqual([],items)
        self.assertEqual(3,sum(excluded.values()))

    def test_partials_are_not_presented_as_complete_trades(self):
        items,excluded=exercises([self.row(),self.row(id=2,parent_trade_id=1)],'v1','paper')
        self.assertFalse(items)
        self.assertEqual(2,sum(excluded.values()))

    def test_recorded_fill_references_are_labeled(self):
        items,_=exercises([self.row(entry_order_id='a',exit_order_id='b',entry_fill_time='t',exit_fill_time='t')],'v1','live')
        self.assertIn('Live trade journal with recorded broker fill references',items[0]['source'])
