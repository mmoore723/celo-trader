"""Expiration exclusions remain distinct from provider failures and trade losses."""
from contextlib import ExitStack
from datetime import date, datetime
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from broker.tradier_chain import TradierChainMixin
from trading.research_contract_selection import select_research_contract
from trading.loop.research_pass import market_readers
from trading.entry.candidate_observation import observe_candidate_contract
from strategy_health.research_matrix import _contract_selection_message, _contract_selection_reasons


class Client(TradierChainMixin):
    api_key = 'test-fixture'

    def __init__(self, response):
        self._get = Mock(return_value=response)


class ResearchExpirationDetailsTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('broker.tradier_chain._market_date', return_value=date(2026, 9, 10))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_sept18_exists_but_is_outside_sept10_weekly_window(self):
        client = Client({'expirations': {'date': ['2026-09-18', '2026-10-16']}})
        detail = client.get_research_expiration_details('COO')
        self.assertEqual('no_expirations_in_window', detail['reason'])
        self.assertEqual([], detail['expirations'])
        self.assertEqual(2, detail['listed_count'])
        self.assertEqual('2026-09-18', detail['nearest_expiration'])
        self.assertEqual((0, 7), (detail['minimum_dte'], detail['maximum_dte']))
        client._get.assert_called_once()

    def test_selected_dates_preserve_native_order_and_limit(self):
        client = Client({'expirations': {'date': ['2026-09-18', '2026-09-11', '2026-09-16']}})
        for low, high, limit in ((0, 7, 8), (7, 21, 3), (3, 5, 8), (0, 7, 1)):
            self.assertEqual(client.get_expirations('AAPL', minimum_dte=low, maximum_dte=high, limit=limit),
                             client.get_research_expiration_details('AAPL', minimum_dte=low, maximum_dte=high, limit=limit)['expirations'])

    def test_single_date_and_empty_listing(self):
        detail = Client({'expirations': {'date': '2026-09-11'}}).get_research_expiration_details('AAPL')
        self.assertEqual(['2026-09-11'], detail['expirations'])
        detail = Client({'expirations': {'date': []}}).get_research_expiration_details('NONE')
        self.assertEqual('no_listed_expirations', detail['reason'])
        self.assertEqual(0, detail['listed_count'])

    def test_unknown_body_is_not_proof_of_no_options(self):
        for response in ({}, None, {'expirations': None}, {'expirations': {'date': None}},
                         {'expirations': {'date': ['bad-date']}}):
            detail = Client(response).get_research_expiration_details('TEST')
            self.assertEqual('expiration_data_unavailable', detail['reason'])
            self.assertIsNone(detail['listed_count'])

    def test_failed_request_does_not_store_exception_text(self):
        client = Client(None)
        error = RuntimeError('sensitive error URL or credential')
        error.response = SimpleNamespace(status_code=429)
        client._get.side_effect = error
        detail = client.get_research_expiration_details('TEST')
        self.assertEqual('request_failed', detail['lookup_status'])
        self.assertEqual(429, detail['http_status'])
        self.assertNotIn('sensitive', json.dumps(detail))

    def test_missing_key_does_not_request(self):
        client = Client(None)
        client.api_key = ''
        detail = client.get_research_expiration_details('TEST')
        self.assertEqual('missing_credentials', detail['lookup_status'])
        client._get.assert_not_called()

    def test_worker_and_candidate_persist_window_failure_without_entry_price(self):
        client = Client({'expirations': {'date': ['2026-09-18']}})
        _, reader = market_readers(Mock(), client)
        self.assertTrue(callable(reader.get_research_expiration_details))
        self.assertFalse(hasattr(reader, '_get'))
        signal = SimpleNamespace(strategy_id='V2_TREND_CONT', direction='bullish',
                                 meta={'shadow_candidate_id': 'test-play'})
        with ExitStack() as stack:
            stack.enter_context(patch('trading.entry.candidate_observation.record_router_candidate'))
            snapshot = stack.enter_context(patch('trading.entry.candidate_observation.snapshot_candidate_plan'))
            quote = stack.enter_context(patch('trading.entry.candidate_observation.record_candidate_option_quote'))
            observe_candidate_contract(ticker='COO', signal=signal, underlying_price=100,
                                       tradier=reader, balance=0, risk=Mock(), settings={}, research_only=True)
        preview = snapshot.call_args.args[0]['contract_preview']
        self.assertEqual('no_expirations_in_window', preview['reason'])
        self.assertEqual('2026-09-18', preview['expiration_lookup']['nearest_expiration'])
        quote.assert_not_called()
        reasons = _contract_selection_reasons([{'entry_ask': None, 'metadata_json': json.dumps({'manual_plan': {'contract_preview': preview}})}])
        explanation, test = _contract_selection_message(reasons)
        self.assertIn('date window', explanation)
        self.assertIn('separate', test)

    def test_legacy_reader_keeps_unknown_no_expirations_reason(self):
        client = SimpleNamespace(get_expirations=lambda *a, **kw: [], get_option_chain=Mock())
        contract, info = select_research_contract(client, 'AAPL', 'bullish', 100, 'V2_TREND_CONT')
        self.assertIsNone(contract)
        self.assertEqual('no_expirations', info['reason'])
        self.assertNotIn('expiration_lookup', info)

    def test_distinct_statuses_have_distinct_next_actions(self):
        for reason, phrase in (('no_listed_expirations', 'availability'),
                               ('expiration_data_unavailable', 'lookup status')):
            _, action = _contract_selection_message({reason: 1})
            self.assertIn(phrase, action)


if __name__ == '__main__':
    unittest.main()
