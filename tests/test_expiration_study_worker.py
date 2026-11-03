"""Worker enrollment, read sharing, account boundaries and primary-data isolation."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from auth.context import get_current_user_id
from config.research_snapshot import research_settings_snapshot
from database import expiration_study as ledger
from tests import test_authored_exit_capture as authored_fixture
from strategy_health.expiration_study_exits import normalized_profit
from tests.test_expiration_study_selection import Clock, Reader, SETUP
from trading import expiration_study as worker
from trading.expiration_study_selection import select


class SharedReadTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.source = Reader(self.clock)
        self.reader = worker.SharedReads(self.source, self.clock)

    def choose(self):
        return select(self.reader, ticker='COO', direction='bullish', underlying_price=100,
                      setup_at=self.clock.now, clock=self.clock)

    def test_forty_overlapping_setups_share_reads_without_dropping_any(self):
        results = [self.choose() for _ in range(40)]
        self.assertTrue(all(row['status'] == 'selected' for row in results))
        self.assertEqual(['listing', 'chain', 'quote'], self.source.calls)
        self.assertEqual(dict(expirations=1, chain=1, quote=1), self.reader.reads)

    def test_returned_cache_values_cannot_mutate_other_plays(self):
        first = self.choose()
        first['contract']['ask'] = 100
        self.assertEqual(2, self.choose()['contract']['ask'])
        self.assertEqual(2, self.source.quote['ask'])

    def test_quotes_refresh_after_five_seconds_but_listing_is_shared(self):
        self.choose()
        self.clock.now += timedelta(seconds=6)
        self.source.quote.update(bid_date=self.clock.now.isoformat(), ask_date=self.clock.now.isoformat())
        self.assertEqual('selected', self.choose()['status'])
        self.assertEqual(dict(expirations=1, chain=2, quote=2), self.reader.reads)

    def test_shared_quote_still_has_to_pass_exchange_freshness(self):
        self.source.quote.update(bid_date=(SETUP-timedelta(seconds=59)).isoformat())
        self.assertEqual('selected', self.choose()['status'])
        self.clock.now += timedelta(seconds=3)
        self.assertEqual('entry_quote_unusable', self.choose()['reason'])
        self.assertEqual(1, self.reader.reads['quote'])

    def test_provider_failure_is_shared_then_retried_after_ttl(self):
        self.source.get_option_quote = Mock(side_effect=RuntimeError('unavailable'))
        for _ in range(40):
            self.assertIsNone(self.choose()['contract'])
        self.assertEqual(1, self.source.get_option_quote.call_count)
        self.clock.now += timedelta(seconds=6)
        self.source.get_option_quote.side_effect = None
        self.source.get_option_quote.return_value = self.source.quote
        self.assertEqual('selected', self.choose()['status'])
        self.assertEqual(2, self.source.get_option_quote.call_count)

    def test_listing_cannot_cross_market_date_or_request_bounds(self):
        self.reader.get_research_expiration_details('COO', minimum_dte=8)
        self.reader.get_research_expiration_details('COO', minimum_dte=9)
        self.clock.now += timedelta(days=1)
        self.reader.get_research_expiration_details('COO', minimum_dte=8)
        self.assertEqual(3, self.reader.reads['expirations'])


class ExpirationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authored_fixture.AuthoredExitCaptureTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.seed('study')
        self.settings = dict(active_broker_account_id='a', paper_trading=True,
                             broker_provider='alpaca', shadow_ledger_enabled=True)
        self.clock = Clock()
        self.clock.now = datetime(2026, 9, 10, 10, 5, 3)
        self.source = Reader(self.clock)
        self.symbol = 'META260918C00101000'
        self.source.chain[0]['symbol'] = self.symbol
        self.source.quote.update(symbol=self.symbol, source_symbol=self.symbol,
                                 bid_date=self.clock.now.isoformat(), ask_date=self.clock.now.isoformat())
        self.reader = worker.SharedReads(self.source, self.clock)
        with self.fixture.connect() as conn:
            row = conn.execute('SELECT * FROM shadow_candidates WHERE candidate_id=?', ('study',)).fetchone()
        self.signal = SimpleNamespace(strategy_id=row['strategy_id'], direction='bullish',
                                      meta={'shadow_candidate_id': 'study'})
        self.connection_patch = patch.object(worker, 'get_conn', self.fixture.connect)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)

    def enroll(self, **changes):
        args = dict(signal=self.signal, ticker='META', price=100, reader=self.reader,
                    settings=self.settings, clock=self.clock)
        args.update(changes)
        worker.observe(**args)

    def rows(self, account='a'):
        with self.fixture.connect() as conn:
            return ledger.load(conn, account=account)

    def primary(self):
        with self.fixture.connect() as conn:
            return {table: [tuple(row) for row in conn.execute('SELECT * FROM '+table)]
                    for table in ('shadow_candidates', 'candidate_option_quote_observations',
                                  'research_strategy_exits')}

    def test_unpinned_worker_never_reads_or_enrolls(self):
        self.enroll()
        self.assertEqual([], self.source.calls)
        self.assertEqual([], self.rows())

    def test_account_mode_provider_and_user_must_match_pinned_context(self):
        for changes in ({'active_broker_account_id': 'b'}, {'paper_trading': False},
                        {'broker_provider': 'tradier'}):
            with research_settings_snapshot(get_current_user_id(), self.settings):
                self.enroll(settings={**self.settings, **changes})
        with research_settings_snapshot('a-different-user', self.settings):
            self.enroll()
        with research_settings_snapshot(get_current_user_id(), {**self.settings, 'shadow_ledger_enabled': False}):
            self.enroll()
        self.assertEqual([], self.source.calls)
        self.assertEqual([], self.rows())

    def test_existing_observations_and_stopped_work_are_not_backfilled(self):
        with research_settings_snapshot(get_current_user_id(), self.settings):
            self.enroll(stopped=lambda: True)
            self.signal.meta['research_existing_candidate'] = True
            self.enroll()
        self.assertEqual([], self.source.calls)

    def test_wrong_candidate_identity_and_account_never_request_prices(self):
        with research_settings_snapshot(get_current_user_id(), self.settings):
            self.enroll(ticker='AAPL')
            self.signal.direction = 'bearish'
            self.enroll()
            self.signal.direction = 'bullish'
        other = {**self.settings, 'active_broker_account_id': 'b'}
        with research_settings_snapshot(get_current_user_id(), other):
            self.enroll(settings=other)
        self.assertEqual([], self.source.calls)

    def test_first_observation_survives_restart_without_changing_primary_data(self):
        before = self.primary()
        with research_settings_snapshot(get_current_user_id(), self.settings):
            self.enroll()
            first = self.rows()
            self.reader = worker.SharedReads(self.source, self.clock)
            self.source.quote['ask'] = 8
            self.enroll()
        self.assertEqual(1, len(first))
        self.assertEqual(first, self.rows())
        self.assertEqual([], self.rows('b'))
        self.assertEqual(before, self.primary())
        self.assertEqual(['listing', 'chain', 'quote'], self.source.calls)

    def test_real_authored_exit_is_captured_without_mutating_primary_result(self):
        self.fixture.capture()
        before = self.primary()
        with research_settings_snapshot(get_current_user_id(), self.settings):
            self.enroll()
            self.clock.now = self.fixture.now
            market = Mock()
            values = [dict(t=row.time.tz_localize('America/New_York').tz_convert('UTC').isoformat(), o=row.open, h=row.high, l=row.low,
                           c=row.close, v=getattr(row, 'volume', 100)) for row in self.fixture.frame.itertuples()]
            market.get_session_bars.return_value = (values, None, None)
            options = Mock()
            options.get_option_quote.return_value = dict(symbol=self.symbol, source_symbol=self.symbol,
                                                        bid=1.2, ask=1.3, bid_date='2026-09-10T10:15:30')
            stats = worker.capture(market=market, options=options, settings=self.settings,
                                   worker_state={}, stopped=lambda: False, clock=self.clock)
        self.assertEqual(0, stats['failed_rows'])
        state = self.rows()[0]['state']
        self.assertEqual('priced', state['status'])
        self.assertEqual('underlying_stop', state['reason'])
        self.assertEqual(-83.3, normalized_profit(state))
        options.get_option_quote.assert_called_once_with(self.symbol)
        self.assertEqual(before, self.primary())

    def test_low_premium_enrolls_and_captures_separately(self):
        from trading.expiration_study_selection import LOW_PREMIUM_PROFILE
        before = self.primary()
        self.source.chain[0].update(bid=.49, ask=.50)
        self.source.quote.update(bid=.49, ask=.50)
        with research_settings_snapshot(get_current_user_id(), self.settings):
            self.enroll()
            self.enroll()
        with self.fixture.connect() as conn:
            low = ledger.load(conn, account='a', profile=LOW_PREMIUM_PROFILE)
        self.assertEqual(1,len(low))
        self.assertEqual('collecting',low[0]['state']['status'])
        self.assertNotEqual('collecting',self.rows()[0]['state']['status'])
        stats = ledger.capture(connect=self.fixture.connect,account='a',
                               bars_lookup=lambda ticker:self.fixture.frame,
                               quote_lookup=lambda symbol:dict(symbol=symbol,source_symbol=symbol,bid=.3,ask=.31,bid_date='2026-09-10T10:15:30'),
                               clock=lambda:self.fixture.now)
        self.assertEqual(0,stats['failed_rows'])
        with self.fixture.connect() as conn:
            low = ledger.load(conn,account='a',profile=LOW_PREMIUM_PROFILE)
        self.assertEqual('priced',low[0]['state']['status'])
        self.assertEqual(before,self.primary())


if __name__ == '__main__':
    unittest.main()
