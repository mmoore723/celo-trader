"""The longer-expiration selector cannot fabricate prices or change its profile."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from trading.expiration_study_selection import PROFILE, select


SETUP = datetime(2026, 9, 10, 10, 0)


def option(symbol='COO260918C00101000', strike=101, bid=1.95, ask=2.0):
    return dict(symbol=symbol, strike=strike, bid=bid, ask=ask)


class Clock:
    now = SETUP

    def __call__(self):
        return self.now


class Reader:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.listing = dict(lookup_status='ok', as_of_date='2026-09-10',
                            expirations=['2026-09-25', '2026-09-18'])
        self.chain = [option()]
        self.quote = dict(symbol=option()['symbol'], source_symbol=option()['symbol'],
                          bid=1.95, ask=2.0, bid_date=SETUP.isoformat(), ask_date=SETUP.isoformat())
        self.delay_at = None

    def _record(self, operation):
        self.calls.append(operation)
        if self.delay_at == operation:
            self.clock.now += timedelta(seconds=61)

    def get_research_expiration_details(self, ticker, **kwargs):
        self._record('listing')
        self.bounds = kwargs
        return self.listing

    def get_research_option_chain(self, ticker, expiry, option_type):
        self._record('chain')
        self.chain_request = (ticker, expiry, option_type)
        return self.chain

    def get_option_quote(self, symbol):
        self._record('quote')
        self.quoted_symbol = symbol
        return self.quote

    def place_option_order(self, *args, **kwargs):
        raise AssertionError('Research cannot order')


class LongerExpirationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.reader = Reader(self.clock)

    def run_selection(self, **changes):
        args = dict(ticker='COO', direction='bullish', underlying_price=100,
                    setup_at=SETUP, clock=self.clock)
        args.update(changes)
        return select(self.reader, **args)

    def test_nearest_expiry_is_sorted_and_rule_is_frozen(self):
        result = self.run_selection()
        self.assertEqual(PROFILE, result['profile_version'])
        self.assertEqual('selected', result['status'])
        self.assertEqual(('COO', '2026-09-18', 'call'), self.reader.chain_request)
        self.assertEqual(dict(minimum_dte=8, maximum_dte=21, limit=128), self.reader.bounds)
        self.assertEqual(['listing', 'chain', 'quote'], self.reader.calls)
        self.assertEqual(dict(expirations=1, chain=1, quote=1), result['reads'])

    def test_refresh_ask_is_used_not_chain_ask(self):
        self.reader.quote.update(bid=2.03, ask=2.1)
        result = self.run_selection()
        self.assertEqual(2.1, result['contract']['ask'])
        self.assertEqual(SETUP.isoformat(), result['contract']['entry_quote_at'])

    def test_low_premium_profile_is_separate_and_spread_limit_unchanged(self):
        from trading.expiration_study_selection import LOW_PREMIUM_PROFILE
        self.reader.chain = [option(bid=.49, ask=.50)]
        self.reader.quote.update(bid=.49, ask=.50)
        self.assertEqual('no_contract_in_profile', self.run_selection()['reason'])
        result = self.run_selection(profile=LOW_PREMIUM_PROFILE)
        self.assertEqual('selected', result['status'])
        self.assertEqual(LOW_PREMIUM_PROFILE, result['profile_version'])
        self.assertEqual((.25,1.49,.08), (result['minimum_ask'],result['maximum_ask'],result['maximum_spread_pct']))
        self.reader.chain = [option(bid=.40, ask=.50)]
        self.assertEqual('no_contract_in_profile', self.run_selection(profile=LOW_PREMIUM_PROFILE)['reason'])

    def test_unknown_profile_cannot_silently_change_limits(self):
        with self.assertRaises(KeyError):
            self.run_selection(profile='unknown')

    def test_chain_inputs_and_listing_are_not_mutated(self):
        before = deepcopy((self.reader.listing, self.reader.chain, self.reader.quote))
        self.run_selection()
        self.assertEqual(before, (self.reader.listing, self.reader.chain, self.reader.quote))

    def test_no_later_expiry_retry_when_nearest_has_no_contract(self):
        self.reader.chain = []
        result = self.run_selection()
        self.assertEqual('no_contract_in_profile', result['reason'])
        self.assertEqual(['listing', 'chain'], self.reader.calls)

    def test_request_delays_expire_entry_without_further_reads(self):
        for operation, expected in [('listing', ['listing']), ('chain', ['listing', 'chain']),
                                    ('quote', ['listing', 'chain', 'quote'])]:
            self.setUp()
            self.reader.delay_at = operation
            result = self.run_selection()
            self.assertEqual('setup_expired', result['reason'])
            self.assertEqual(expected, self.reader.calls)
            self.assertIsNone(result['contract'])

    def test_stale_future_wrong_contract_and_unknown_quotes_fail(self):
        for change in ({'bid_date': (SETUP-timedelta(seconds=61)).isoformat()},
                       {'ask_date': (SETUP-timedelta(seconds=61)).isoformat()},
                       {'bid_date': (SETUP+timedelta(seconds=1)).isoformat()},
                       {'source_symbol': 'WRONG'}, {'ask_date': None}):
            self.setUp()
            self.reader.quote.update(change)
            self.assertEqual('entry_quote_unusable', self.run_selection()['reason'])
        for value in (None, 'bad', 12, []):
            self.reader.quote = value
            self.assertEqual('entry_quote_unusable', self.run_selection()['reason'])

    def test_expired_future_or_off_session_setup_never_requests(self):
        for setup in (SETUP-timedelta(seconds=61), SETUP+timedelta(seconds=1),
                      SETUP-timedelta(days=1), SETUP.replace(hour=8)):
            self.assertEqual('setup_expired', self.run_selection(setup_at=setup)['reason'])
        self.assertEqual([], self.reader.calls)

    def test_quote_revalidation_does_not_fall_back_to_another_contract(self):
        self.reader.chain.append(option('COO260918C00102000', 102))
        self.reader.quote.update(ask=10.50, bid=10.49)
        result = self.run_selection()
        self.assertEqual('refreshed_quote_outside_profile', result['reason'])
        self.assertEqual(['listing', 'chain', 'quote'], self.reader.calls)

    def test_put_selection_and_ties_are_deterministic(self):
        symbol='COO260918P00099000'
        self.reader.chain = [option('COO260918P00098000', 98), option(symbol, 99), option('COO260918P00101000', 101)]
        self.reader.quote.update(symbol=symbol, source_symbol=symbol)
        result = self.run_selection(direction='bearish')
        self.assertEqual(symbol, result['contract']['symbol'])
        self.assertEqual('put', self.reader.chain_request[2])

    def test_invalid_chain_values_do_not_become_prices(self):
        self.reader.chain = [option(ask=float('nan')), option(bid=0), option(strike=0),
                             option(ask=12), option(strike=99), option(symbol=''), option(bid=1.5)]
        self.assertEqual('no_contract_in_profile', self.run_selection()['reason'])

    def test_wrong_listing_date_and_no_in_window_expiry_fail(self):
        self.reader.listing['as_of_date'] = '2026-09-09'
        self.assertEqual('expiration_date_mismatch', self.run_selection()['reason'])
        self.reader.listing.update(as_of_date='2026-09-10', expirations=['2026-09-11', '2026-10-02'])
        self.assertEqual('no_expirations_in_window', self.run_selection()['reason'])

    def test_month_date_boundary_does_not_use_another_days_listing(self):
        self.clock.now = datetime(2026, 10, 1, 10)
        self.assertEqual('expiration_date_mismatch', self.run_selection(setup_at=self.clock.now)['reason'])

    def test_unknown_capability_cannot_fall_back_to_execution_selector(self):
        self.reader = SimpleNamespace(get_option_chain=lambda *a: self.fail('wrong selector'))
        self.assertEqual('research_reader_unavailable', self.run_selection()['reason'])

    def test_wrong_root_expiry_type_strike_and_adjusted_root_are_rejected(self):
        for symbol in ('OTHER260918C00101000','COO260925C00101000','COO260918P00101000',
                       'COO260918C00102000','COO1260918C00101000','unparseable'):
            self.setUp(); self.reader.chain=[option(symbol)]
            result=self.run_selection()
            self.assertEqual('contract_identity_mismatch',result['reason'])
            self.assertEqual(['listing','chain'],self.reader.calls)


if __name__ == '__main__':
    unittest.main()
