import unittest

from research.jobs.replay_enabled_available_portfolio import normalize, run_arm


SETTINGS = dict(growth_mode=False, risk_per_trade=.1, max_concurrent_positions=3,
                daily_loss_hard_cap_pct=30, max_daily_loss_pct=.1, kill_lock_hours=24,
                paper_trading=True)
DAY = '2026-06-01'
SID = 'V2_SPY_TREND_CONT'


def row(identity, sid=SID, ticker='SPY', day=DAY, minute=0, status='priced'):
    start, end = f'{day}T10:{minute:02}:00-04:00', f'{day}T10:{minute+1:02}:00-04:00'
    contract = ticker + ' 260612C00100000'
    path = [dict(time=start, bid='0.99', ask='1', bid_size='5', ask_size='1', contract=contract),
            dict(time=end, bid='1.10', ask='1.12', bid_size='5', ask_size='1', contract=contract)]
    result = dict(id=identity, strategy_id=sid, ticker=ticker, entry_time=start,
                  status=status, family='fixture', path=path)
    if status == 'priced':
        result['trade'] = dict(id=identity, strategy_id=sid, ticker=ticker, contracts=1,
            contract_symbol=contract, entry_time=start, exit_time=end, entry_price='1', entry_bid='.99',
            entry_size='1', exit_price='1.10')
    return result


class EnabledPortfolioTests(unittest.TestCase):
    def run_rows(self, rows, **kwargs):
        return run_arm(rows, SETTINGS, [DAY], kwargs.get('friction', 0))

    def test_shared_ticker_competes_across_strategy_names(self):
        result = self.run_rows([row('a'), row('b', sid='V2_SPY_AFTERNOON_FVG')])
        self.assertEqual(1, result['max_open'])
        self.assertEqual({'ticker_already_open': 1}, result['skip_counts'])
        self.assertEqual(6.7, result['net_pnl'])
        self.assertEqual(1, len(result['tied_entry_clocks']))

    def test_different_tickers_share_one_equity_ledger(self):
        result = self.run_rows([row('a'), row('b', sid='V2_TSLA_TWO_LEG_TREND_PULLBACK', ticker='TSLA')])
        self.assertEqual(2, result['max_open'])
        self.assertEqual(5013.4, result['ending_equity'])
        self.assertEqual(203.3, result['peak_committed_debit'])
        self.assertEqual(result['net_pnl'], sum(result['daily_pnl'].values()))

    def test_input_order_cannot_select_winner_at_tied_entry_clock(self):
        rows = [row('b', sid='V2_SPY_AFTERNOON_FVG'), row('a')]
        self.assertEqual(self.run_rows(rows), self.run_rows(list(reversed(rows))))

    def test_highly_profitable_outside_period_trade_does_not_leak_in(self):
        outside = row('outside', day='2026-05-29')
        outside['trade']['exit_price'] = '99'
        result = self.run_rows([row('inside'), outside])
        self.assertEqual(2, result['source_entries'])
        self.assertEqual(1, result['inside_calendar'])
        self.assertEqual(1, result['outside_calendar'])
        self.assertEqual(6.7, result['net_pnl'])

    def test_missing_option_is_counted_not_given_a_zero_return(self):
        result = self.run_rows([row('a'), row('b', status='no_affordable_contract')])
        self.assertEqual(2, result['inside_calendar'])
        self.assertEqual(1, result['priced_entries'])
        self.assertTrue(result['unresolved_price_evidence'])
        self.assertEqual({'priced': 1, 'no_affordable_contract': 1}, result['inside_statuses'])

    def test_empty_native_pair_is_not_claimed_as_no_setup_or_all_six_acceptance(self):
        result = self.run_rows([row('a')])
        self.assertEqual(7, len(result['by_pair']))
        self.assertEqual(0, result['by_pair']['V2_ORB_PULLBACK|TSLA']['retained_opportunities'])
        self.assertFalse(result['by_pair']['V2_ORB_PULLBACK|TSLA']['complete_opportunity_coverage'])
        self.assertFalse(result['deployable'])
        self.assertFalse(result['all_six_acceptance'])

    def test_exit_depth_insufficiency_invalidates_price_evidence(self):
        r = row('a'); r['path'][-1]['bid_size'] = '0.5'
        result = self.run_rows([r])
        self.assertEqual(['a'], result['insufficient_exit_depth'])
        self.assertTrue(result['unresolved_price_evidence'])

    def test_conflicting_quotes_for_same_contract_and_minute_rejected(self):
        a, b = row('a'), row('b', sid='V2_SPY_AFTERNOON_FVG')
        b['path'][0]['bid'] = '.9'
        with self.assertRaisesRegex(ValueError, 'Conflicting shared-contract'):
            self.run_rows([a, b])

    def test_extra_spread_cost_applies_to_both_sides(self):
        base, stressed = self.run_rows([row('a')]), self.run_rows([row('a')], friction=.01)
        self.assertAlmostEqual(2, base['net_pnl']-stressed['net_pnl'])

    def test_displacement_uses_original_structural_exit(self):
        r = row('a', sid='CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG', ticker='TSLA')
        first, last = r['path']
        original = dict(id='a', ticker='TSLA', entry_time=r['entry_time'], paths={'control':r['path']},
            selections={'control':first}, legs={'control': {
                'structural':dict(status='priced',exit_time=last['time'],exit_bid=last['bid']),
                'timer':dict(status='priced',exit_time='2026-06-01T11:00:00-04:00',exit_bid='99')}})
        normalized = normalize({'displacement':dict(rows=[original])}, 'control')
        self.assertEqual(last['time'], normalized[0]['trade']['exit_time'])
        self.assertEqual(last['bid'], normalized[0]['trade']['exit_price'])

    def test_wrong_native_ticker_is_rejected(self):
        r = row('a', ticker='META')
        original = dict(id='a', ticker='META', entry_time=r['entry_time'],
            selections={'control':r['path'][0]}, paths={'control':r['path']},
            legs={'control':{'structural':dict(status='priced',exit_time=r['path'][-1]['time'],exit_bid='1.10')}})
        with self.assertRaisesRegex(ValueError, 'Not an enabled native'):
            normalize({'displacement':dict(rows=[original])}, 'control')

    def test_empty_or_unsorted_calendar_rejected(self):
        for calendar in ([], ['2026-06-02', DAY], [DAY, DAY]):
            with self.assertRaisesRegex(ValueError, 'Common calendar'):
                run_arm([row('a')], SETTINGS, calendar, 0)


if __name__ == '__main__':
    unittest.main()
