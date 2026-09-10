"""Research's declared screen must not inherit hidden order-entry gates."""
from datetime import datetime
import unittest
from unittest.mock import patch

from broker.tradier_chain import TradierChainMixin
from trading.research_contract_selection import select_research_contract


def option(symbol='TEST_C', **changes):
    return dict(symbol=symbol, option_type='call', strike=101,
                bid=9.2, ask=9.8, open_interest=10, volume=20, **changes)


class Client(TradierChainMixin):
    api_key = 'fixture-not-a-secret'

    def __init__(self, rows):
        self.rows = rows
        self.reads = 0

    def _get(self, path, params):
        self.reads += 1
        return {'options': {'option': self.rows}}

    def get_expirations(self, ticker, **kwargs):
        return ['2026-09-11']


class ResearchChainIsolationTests(unittest.TestCase):
    def test_research_keeps_declared_eligible_contract_execution_rejects(self):
        client = Client([option()])
        self.assertEqual([], client.get_option_chain('TEST', '2026-09-11'))
        with patch('trading.research_contract_selection._now_et', return_value=datetime(2026,9,10,14)):
            chosen, info = select_research_contract(client,'TEST','bullish',100,'V2_SPY_AFTERNOON_FVG')
        self.assertEqual('TEST_C', chosen['symbol'])
        self.assertEqual(10, chosen['open_interest'])
        self.assertEqual('research_quote_validity_v1', info['chain_screen'])
        self.assertFalse(info['upstream_chain_liquidity_filtered'])
        self.assertEqual([], client.get_option_chain('TEST', '2026-09-11'))

    def test_research_still_rejects_wide_spreads_and_outside_premium(self):
        for changes, reason in [({'bid':8},'illiquid'),({'ask':11,'bid':10.9},'filtered')]:
            row = option(); row.update(changes)
            with patch('trading.research_contract_selection._now_et',return_value=datetime(2026,9,10,14)):
                chosen, info = select_research_contract(Client([row]),'TEST','bullish',100,'V2_SPY_AFTERNOON_FVG')
            self.assertIsNone(chosen)
            self.assertEqual(reason,info['reason'])

    def test_invalid_quotes_are_not_research_prices(self):
        for changes in ({'bid':0},{'ask':9},{'bid':float('nan')},
                        {'ask':float('inf')},{'strike':0},{'symbol':''},{'bid':'bad'}):
            row=option();row.update(changes)
            self.assertEqual([],Client([row]).get_research_option_chain('TEST','2026-09-11'))

    def test_puts_and_existing_execution_eligibility_are_preserved(self):
        row=option();row.update(option_type='put',bid=4.9,ask=5,open_interest=200,strike=99)
        client=Client([row])
        self.assertEqual([],client.get_research_option_chain('TEST','2026-09-11','call'))
        self.assertEqual(client.get_option_chain('TEST','2026-09-11','put'),
                         client.get_research_option_chain('TEST','2026-09-11','put'))

    def test_single_object_response_and_no_extra_fetch_per_read(self):
        client=Client(option())
        self.assertEqual(1,len(client.get_research_option_chain('TEST','2026-09-11')))
        self.assertEqual(1,client.reads)


if __name__ == '__main__':
    unittest.main()
