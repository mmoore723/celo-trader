"""No network/order side effects: exercise the exact pre-submit capacity gate."""
import unittest
from unittest.mock import Mock, patch
from risk.entry_capacity import available_entry_quantity, check_broker_entry_capacity


class EntryCapacityTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(account={'equity':5000, 'cash':5000, 'options_buying_power':5000},
                         positions=[], orders=[], symbol='SPY_OPTION', requested_quantity=3,
                         limit_price=5, max_positions=3)

    def call(self, **changes):
        return available_entry_quantity(**{**self.args, **changes})

    def test_fee_reserve_prevents_rounding_over_buying_power(self):
        self.args['account']['options_buying_power'] = 1000
        self.assertEqual((1, None), self.call())

    def test_never_uses_leveraged_stock_buying_power(self):
        self.args['account'].update(options_buying_power=100, buying_power=20000)
        self.assertEqual((0, 'options_buying_power'), self.call())

    def test_cash_is_also_a_ceiling(self):
        self.args['account']['cash'] = 600
        self.assertEqual((1, None), self.call())

    def test_recovered_and_manual_positions_count(self):
        rows = [{'symbol':f'P{i}', 'qty':1, 'strategy_id':'RECOVERED_UNTRACKED'} for i in range(3)]
        self.assertEqual((0, 'account_position_limit'), self.call(positions=rows))

    def test_pending_orders_reserve_slots(self):
        rows = [{'symbol':f'P{i}', 'side':'buy'} for i in range(3)]
        self.assertEqual((0, 'account_position_limit'), self.call(orders=rows))

    def test_same_symbol_position_and_order_count_once(self):
        self.assertEqual((3, None), self.call(max_positions=2, positions=[{'symbol':'P', 'qty':1}],
                                             orders=[{'symbol':'P', 'side':'sell'}]))

    def test_duplicate_contract_blocked(self):
        self.assertEqual((0, 'contract_already_open_or_pending'), self.call(
            orders=[{'option_symbol':'SPY_OPTION', 'symbol':'SPY', 'side':'buy_to_open'}]))

    def test_zero_position_does_not_count(self):
        self.assertEqual((3, None), self.call(positions=[{'symbol':'P', 'qty':0}]))

    def test_missing_and_nonfinite_snapshots_fail_closed(self):
        for changes in [{'positions':None}, {'orders':None}, {'account':{}},
                        {'positions':[{'symbol':'P', 'qty':float('nan')}]},
                        {'orders':[{'symbol':'P'}]}]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, KeyError)):
                self.call(**changes)
        for field in ['cash', 'options_buying_power', 'equity']:
            for value in [float('nan'), float('inf')]:
                with self.assertRaises(ValueError):
                    self.call(account={**self.args['account'], field:value})

    def test_zero_and_negative_capacity_do_not_fallback(self):
        for field in ['cash', 'options_buying_power', 'equity']:
            self.assertEqual(0, self.call(account={**self.args['account'], field:0})[0])
            self.assertEqual(0, self.call(account={**self.args['account'], field:-1})[0])

    def test_broker_block_prevents_entry(self):
        self.assertEqual((0, 'broker_account_blocked'), self.call(
            account={**self.args['account'], 'trading_blocked':True}))

    def test_refresh_rechecks_risk_against_current_equity(self):
        broker, risk = Mock(), Mock()
        broker.get_positions.return_value = []
        broker.get_open_orders.return_value = []
        broker.get_account.return_value = self.args['account']
        risk.calculate_contracts.return_value = 1
        self.assertEqual((1, None), check_broker_entry_capacity(broker, risk,
            symbol='SPY_OPTION', strategy_id='V2_SPY_TREND_CONT', requested_quantity=3,
            limit_price=5, max_positions=3))
        risk.calculate_contracts.assert_called_once_with(5, 5000., strategy_id='V2_SPY_TREND_CONT')
        broker.submit_option_order.assert_not_called()

    def test_slow_or_disconnected_snapshot_never_authorizes(self):
        broker, risk = Mock(), Mock()
        with patch('risk.entry_capacity.time.monotonic', side_effect=[0, 16]), self.assertRaises(ValueError):
            check_broker_entry_capacity(broker, risk, symbol='P', strategy_id='S',
                                        requested_quantity=1, limit_price=5, max_positions=3)
        broker.get_positions.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            check_broker_entry_capacity(broker, risk, symbol='P', strategy_id='S',
                                        requested_quantity=1, limit_price=5, max_positions=3)
        broker.submit_option_order.assert_not_called()

if __name__ == '__main__':
    unittest.main()
