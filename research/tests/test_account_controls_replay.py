import unittest
from research.jobs.replay_account_controls import replay

SETTINGS = {'growth_mode': False, 'risk_per_trade': .1, 'max_concurrent_positions': 2,
            'daily_loss_hard_cap_pct': 30, 'max_daily_loss_pct': .1, 'kill_lock_hours': 24}

def trade(id, start='10:00', end='11:00', entry=1, exit=1, qty=1, day='2026-09-08'):
    return {'id': id, 'entry_time': f'{day}T{start}:00', 'exit_time': f'{day}T{end}:00',
            'entry_price': entry, 'exit_price': exit, 'contracts': qty,
            'strategy_id': 'V2_SPY_TREND_CONT'}

class PortfolioTests(unittest.TestCase):
    def test_costs_and_no_premium_as_drawdown(self):
        r = replay([trade(1)], [], SETTINGS, corrected=False)
        self.assertAlmostEqual(4998.7, r['ending_equity'])
        self.assertAlmostEqual(1.3, r['sampled_drawdown'])
        self.assertEqual(0, r['open_at_end'])

    def test_overlap_and_slot_limit(self):
        r = replay([trade(i) for i in range(3)], [], SETTINGS, corrected=False)
        self.assertEqual(2, r['max_open'])
        self.assertEqual('position_limit', r['decisions'][2]['reason'])

    def test_cash_not_leverage(self):
        r = replay([trade(1, entry=30, exit=30), trade(2, entry=30, exit=30)], [], SETTINGS, corrected=False)
        self.assertEqual('settled_cash', r['decisions'][1]['reason'])

    def test_settlement_vs_same_day_reuse(self):
        rows = [trade(1, end='10:30', entry=40, exit=40), trade(2, start='11:00', end='11:30', entry=40, exit=40)]
        self.assertEqual(1, len(replay(rows, [], SETTINGS, corrected=False)['closed']))
        self.assertEqual(2, len(replay(rows, [], SETTINGS, corrected=False, settled_only=False)['closed']))

    def test_next_day_receipts_become_available(self):
        rows = [trade(1, entry=40, exit=40), trade(2, entry=40, exit=40, day='2026-09-09')]
        self.assertEqual(2, len(replay(rows, [], SETTINGS, corrected=False)['closed']))

    def test_production_sizing_rejects_unaffordable_reviewed_contract(self):
        r = replay([trade(1, entry=8.5, exit=7.35)], [], SETTINGS)
        self.assertEqual('existing_risk_budget', r['decisions'][0]['reason'])
        self.assertEqual(5000, r['ending_equity'])

    def test_realized_soft_halt_blocks_next_entry(self):
        rows = [trade(1, entry=10, exit=4), trade(2, start='12:00', end='13:00')]
        r = replay(rows, [], SETTINGS, corrected=False)
        self.assertEqual('daily_loss_halt', r['decisions'][1]['reason'])

    def test_equity_halt_does_not_invent_exit(self):
        rows = [trade(1, entry=20, exit=20), trade(2, start='10:30', end='11:30')]
        q = [{'trade_id': 1, 'observed_at': '2026-09-08T10:15:00', 'bid': 1}]
        r = replay(rows, q, SETTINGS, corrected=False)
        self.assertFalse(r['performance_valid_without_emergency_repricing'])
        self.assertEqual([1], r['unresolved_emergency_exits'])
        self.assertEqual('daily_loss_halt', r['decisions'][1]['reason'])

    def test_losing_streak_and_spread_stress(self):
        rows = [trade(i, day=f'2026-09-{8+i:02}') for i in range(3)]
        r = replay(rows, [], SETTINGS, corrected=False, friction_per_side=.01)
        self.assertAlmostEqual(-9.9, r['net_pnl'])
        self.assertEqual(3, r['longest_losing_streak'])

    def test_exit_before_simultaneous_entry(self):
        s = {**SETTINGS, 'max_concurrent_positions': 1}
        r = replay([trade(1), trade(2, start='11:00', end='12:00')], [], s, corrected=False)
        self.assertEqual(2, len(r['closed']))

    def test_duplicates_and_invalid_intervals_rejected(self):
        for rows in [[trade(1), trade(1)], [trade(1, start='12:00', end='11:00')]]:
            with self.assertRaises(ValueError):
                replay(rows, [], SETTINGS)

    def test_same_contract_cannot_fill_two_strategies_at_once(self):
        rows = [{**trade(i), 'contract_symbol': 'SPY260918C00760000'} for i in range(2)]
        result = replay(rows, [], SETTINGS, corrected=False)
        self.assertEqual(1, len(result['closed']))
        self.assertEqual('contract_already_open_or_pending', result['decisions'][1]['reason'])

    def test_same_contract_can_reenter_after_exit(self):
        rows = [{**trade(1), 'contract_symbol': 'SPY260918C00760000'},
                {**trade(2, start='11:00', end='12:00'), 'contract_symbol': 'SPY260918C00760000'}]
        self.assertEqual(2, len(replay(rows, [], SETTINGS, corrected=False)['closed']))

    def test_initial_spread_is_in_account_drawdown(self):
        result = replay([{**trade(1), 'entry_bid': .8}], [], SETTINGS, corrected=False)
        self.assertAlmostEqual(20.65, result['sampled_drawdown'])

    def test_explicit_sessions_do_not_settle_on_missing_holiday(self):
        rows = [trade(1, entry=40, exit=40, day='2026-06-18'),
                trade(2, entry=40, exit=40, day='2026-06-19'),
                trade(3, entry=40, exit=40, day='2026-06-22')]
        result = replay(rows, [], SETTINGS, corrected=False,
                        settlement_sessions=['2026-06-18', '2026-06-22', '2026-06-23'])
        self.assertEqual('settled_cash', result['decisions'][1]['reason'])
        self.assertEqual('enter', result['decisions'][2]['action'])

    def test_incomplete_calendar_fails_instead_of_inventing_settlement(self):
        with self.assertRaisesRegex(ValueError, 'cover all exits'):
            replay([trade(1)], [], SETTINGS, settlement_sessions=['2026-09-07'])

    def test_last_session_receipts_remain_unsettled_without_fabricated_date(self):
        result = replay([trade(1)], [], SETTINGS, corrected=False,
                        settlement_sessions=['2026-09-08'])
        self.assertAlmostEqual(99.35, result['receipts_without_future_settlement_session'])
        self.assertAlmostEqual(4899.35, result['settled_cash'])
        self.assertAlmostEqual(4998.7, result['ending_equity'])

    def test_entry_size_limits_quantity_without_using_future_exit_size(self):
        result = replay([{**trade(1, qty=3), 'entry_size': 1}], [], SETTINGS, corrected=False)
        self.assertEqual(1, result['closed'][0]['quantity'])

if __name__ == '__main__':
    unittest.main()
