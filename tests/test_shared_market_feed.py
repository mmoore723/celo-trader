"""No real network or orders: feed parity, outages and provenance."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import sqlite3

from broker.shared_market import SharedMarketBroker, FEED_POLICY, stamp_bars
from broker.tradier_market import TradierMarketMixin, ET
from signals import bars_to_df
from database.scanner_candles import record_scanner_candles, load_scanner_candles
from database.schema import _init_db_at


def bars(day='2026-11-06'):
    return [dict(t=f'{day}T14:30:00Z',o=100,h=101,l=99,c=100,v=200)]


class Market(TradierMarketMixin):
    base = 'https://api.tradier.com/v1'
    api_key = 'test'


class SharedFeedTests(TestCase):
    def test_market_and_order_ownership(self):
        execution, market = Mock(), Mock()
        broker = SharedMarketBroker(execution, market)
        broker.get_bars('QQQ', '15Min', 200)
        broker.get_session_bars('QQQ', '1Min')
        broker.get_latest_quote('QQQ')
        broker.get_snapshots(['QQQ'])
        self.assertEqual(4, len(market.mock_calls))
        self.assertFalse(execution.mock_calls)
        broker.place_option_order(symbol='TEST', side='sell')
        broker.get_positions()
        broker.get_account()
        self.assertEqual(3, len(execution.mock_calls))
        market.place_option_order.assert_not_called()

    def test_data_outage_never_calls_alpaca_data_or_disables_exit(self):
        execution = Mock()
        market = SimpleNamespace(get_session_bars=Mock(return_value=([],True,True)),
                                 get_latest_quote=Mock(return_value=None))
        broker = SharedMarketBroker(execution, market)
        self.assertEqual(([],True,True), broker.get_session_bars('SPY','1Min'))
        self.assertIsNone(broker.get_latest_quote('SPY'))
        execution.get_session_bars.assert_not_called()
        execution.get_latest_quote.assert_not_called()
        broker.place_option_order(side='sell', symbol='TEST')
        execution.place_option_order.assert_called_once()

    def test_factory_never_uses_sandbox_token_for_data(self):
        from broker.factory import get_tradier_market_client
        with patch('config.get_api_keys', return_value={'tradier_api_key':'sandbox-only'}):
            market = get_tradier_market_client()
        self.assertEqual('',market.api_key)
        self.assertEqual('https://api.tradier.com/v1',market.base)
        self.assertEqual(([],True), market.get_bars('SPY','1Min'))
        self.assertIsNone(market.get_latest_quote('SPY'))

    def test_no_previous_day_during_session_even_if_clock_fails(self):
        market=Market()
        market.is_market_open=Mock(return_value=False)
        market._timesales=Mock(return_value=[])
        with patch('broker.tradier_market.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,6,10,0,tzinfo=ET)
            self.assertEqual(([],True,False),market.get_session_bars('SPY','1Min'))
        self.assertEqual(1,market._timesales.call_count)

    def test_provider_previous_day_response_rejected(self):
        market=Market()
        market.is_market_open=Mock(return_value=True)
        market._timesales=Mock(return_value=bars('2026-11-05'))
        with patch('broker.tradier_market.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,6,10,0,tzinfo=ET)
            self.assertEqual(([],True,True),market.get_session_bars('SPY','1Min'))

    def test_close_and_after_close_gaps_cannot_become_yesterday(self):
        for hour,minute in [(16,0),(16,1),(20,0)]:
            market=Market();market.is_market_open=Mock(return_value=False)
            market._timesales=Mock(return_value=[])
            with patch('broker.tradier_market.datetime',wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,11,6,hour,minute,tzinfo=ET)
                self.assertEqual(([],True,False),market.get_session_bars('SPY','1Min'))
            self.assertEqual(1,market._timesales.call_count)

    def test_current_session_has_source_and_original_event_time(self):
        market=Market()
        market.is_market_open=Mock(return_value=True)
        market._timesales=Mock(return_value=bars())
        with patch('broker.tradier_market.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,6,10,0,tzinfo=ET)
            result,error,live=market.get_session_bars('SPY','1Min')
        self.assertFalse(error);self.assertTrue(live)
        self.assertEqual(FEED_POLICY,result[0]['data_feed'])
        self.assertEqual(bars()[0]['t'],result[0]['t'])
        self.assertIsNotNone(datetime.fromisoformat(result[0]['received_at']).tzinfo)

    def test_history_timeout_and_rate_limit_return_error_not_another_feed(self):
        for error in (TimeoutError('timeout'),RuntimeError('429')):
            market=Market();market._timesales=Mock(side_effect=error)
            self.assertEqual(([],True),market.get_bars('SPY','5Min',200))
            market._timesales.assert_called_once()

    def test_delayed_credentials_rejected(self):
        market=Market();market.base='https://sandbox.tradier.com/v1'
        market._get=Mock()
        self.assertEqual(([],True),market.get_bars('SPY','5Min'))
        self.assertEqual(([],True,False),market.get_session_bars('SPY','1Min'))
        self.assertIsNone(market.get_latest_quote('SPY'))
        market._get.assert_not_called()

    def test_dataframe_retains_feed(self):
        frame=bars_to_df(stamp_bars(bars(),'https://api.tradier.com/v1'))
        self.assertEqual(FEED_POLICY,frame.attrs['data_feed'])
        self.assertFalse(frame.attrs['fallback_used'])
        self.assertIn('received_at',frame.attrs)

    def test_candle_revisions_preserved_and_foreign_feeds_excluded(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.db';_init_db_at(path)
            @contextmanager
            def connection():
                with sqlite3.connect(path) as conn:
                    conn.row_factory=sqlite3.Row
                    yield conn
            original=bars_to_df(bars())
            fresh=bars_to_df(stamp_bars(bars(),'https://api.tradier.com/v1'))
            fresh.loc[0,'close']=101
            with patch('database.scanner_candles.get_conn',connection):
                record_scanner_candles('SPY',original,broker_account_id='A',source='alpaca')
                record_scanner_candles('SPY',original,broker_account_id='B',source='alpaca')
                record_scanner_candles('SPY',fresh,broker_account_id='A')
                record_scanner_candles('SPY',fresh,broker_account_id='A')
                loaded=load_scanner_candles('SPY',broker_account_id='A',required_source=FEED_POLICY)
                self.assertEqual(101,loaded.iloc[0]['close'])
                self.assertEqual(FEED_POLICY,loaded.attrs['data_feed'])
                self.assertTrue(load_scanner_candles('SPY',broker_account_id='B',required_source=FEED_POLICY).empty)
            with sqlite3.connect(path) as conn:
                self.assertEqual(3,conn.execute('SELECT count(*) FROM scanner_candle_versions').fetchone()[0])
                self.assertEqual(100,conn.execute("SELECT close FROM scanner_candle_versions WHERE source='alpaca' LIMIT 1").fetchone()[0])

    def test_forward_research_and_entry_read_same_provider(self):
        from trading.loop.research_pass import market_readers
        execution=Mock();market=Market()
        market.get_session_bars=Mock(return_value=(stamp_bars(bars(),market.base),False,True))
        market.get_option_quote=Mock();market.get_expirations=Mock();market.get_option_chain=Mock()
        broker=SharedMarketBroker(execution,market)
        research,_=market_readers(broker,market)
        self.assertEqual(broker.get_session_bars('SPY','1Min'),research.get_session_bars('SPY','1Min'))
        execution.get_session_bars.assert_not_called()

    def test_backtest_outage_never_uses_yahoo_or_legacy_cache(self):
        from backtester.market_data import MarketDataMixin
        subject=MarketDataMixin()
        subject.alpaca=SimpleNamespace(feed_policy=FEED_POLICY,get_bars=Mock(return_value=([],True)))
        subject.ticker='SPY';subject.months=1
        with patch('backtest_data_cache.load',return_value=None) as cache, patch('yfinance.download') as yahoo:
            result=subject._load_market_data()
        self.assertIn('No IEX or Yahoo substitution',result['error'])
        self.assertEqual('SPY__'+FEED_POLICY,cache.call_args.args[0])
        yahoo.assert_not_called()

    def test_backtest_extra_timeframe_never_uses_yahoo(self):
        from backtester.fetch import FetchMixin
        subject=FetchMixin();subject.ticker='SPY'
        subject.alpaca=SimpleNamespace(feed_policy=FEED_POLICY,get_bars=Mock(return_value=([],True)))
        with patch('yfinance.download') as yahoo:
            self.assertTrue(subject._fetch_extra_timeframe('1h','2026-11-01','2026-11-06').empty)
        yahoo.assert_not_called()
