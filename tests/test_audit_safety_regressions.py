"""Boundary regressions without credentials, broker calls or running services."""
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pandas as pd

from broker.alpaca_orders import AlpacaOrdersMixin
from database.scanner_candles import record_scanner_candles


class AuditSafetyTests(TestCase):
    def test_invalid_limit_never_calls_broker(self):
        broker = AlpacaOrdersMixin()
        broker.api_key = "test-only"
        broker._post = MagicMock()
        for value in (None, 0, -1, float('nan'), float('inf'), True, 'bad', 0.001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                broker.place_option_order('TEST', 1, 'buy', limit_price=value)
        broker._post.assert_not_called()

    def test_explicit_market_exit_and_valid_limit_are_preserved(self):
        for kind, price in [('market', None), ('limit', 1.25)]:
            with self.subTest(kind=kind):
                broker = AlpacaOrdersMixin()
                broker.api_key = 'test-only'
                broker.base = 'https://paper.invalid'
                broker._post = MagicMock(return_value={'id': 'test-order'})
                broker._wait_for_fill = MagicMock(return_value={
                    'id': 'test-order', 'status': 'filled', 'filled_qty': '1',
                    'filled_avg_price': '1.25', 'confirmed_fill_price': 1.25})
                with patch('broker.alpaca_orders._record_flow'), patch('broker.alpaca_orders.log_event'):
                    broker.place_option_order('TEST', 1, 'sell', order_type=kind,
                        limit_price=price, position_intent='sell_to_close', price_authority='tradier')
                payload = broker._post.call_args.args[1]
                self.assertEqual(kind, payload['type'])
                self.assertEqual('sell_to_close', payload['position_intent'])
                self.assertEqual(kind == 'limit', 'limit_price' in payload)

    def test_receipt_clock_is_aware_in_winter_and_summer(self):
        frame = pd.DataFrame([dict(time=pd.Timestamp('2026-11-04 09:30'),
            open=100, high=101, low=99, close=100, volume=10)])
        for month, expected_hour in [(1, 10), (7, 11)]:
            with self.subTest(month=month), patch('database.scanner_candles.datetime') as clock, \
                    patch('database.scanner_candles.get_conn') as connect:
                clock.now.return_value = datetime(2026, month, 5, 15, tzinfo=timezone.utc)
                record_scanner_candles('TEST', frame, broker_account_id='test')
                clock.now.assert_called_once_with(timezone.utc)
                row = connect.return_value.__enter__.return_value.executemany.call_args.args[1][0]
                self.assertEqual(f'2026-{month:02d}-05T{expected_hour}:00:00', row[-1])
                self.assertEqual('2026-11-04T09:30:00', row[3])

    def test_backend_binding_matches_nginx_upstream(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / 'celo-dashboard.service').read_text()
        self.assertIn('--host 127.0.0.1 --port 8501', unit)
        self.assertNotIn('--host 0.0.0.0', unit)
        self.assertIn('http://127.0.0.1:8501', (root / 'nginx_celotrader.conf').read_text())
