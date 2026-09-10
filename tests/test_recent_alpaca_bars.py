from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack

from broker.alpaca_bars import AlpacaBarsMixin


class Reader(AlpacaBarsMixin):
    data='https://example.test'


def candle(i):
    stamp=datetime(2026,9,1,tzinfo=timezone.utc)+timedelta(minutes=5*i)
    return dict(t=stamp.isoformat().replace('+00:00','Z'),o=100,h=101,l=99,c=100,v=10)


class RecentAlpacaBarsTests(unittest.TestCase):
    def test_limit_selects_newest_not_oldest_window_and_returns_ascending(self):
        client=Reader(); calls=[]
        def endpoint(url,params):
            calls.append(params)
            source=[candle(i) for i in range(12)]
            if params.get('sort')=='desc':
                source.reverse()
            return dict(bars=source[:params['limit']],next_page_token='more')
        client._get=endpoint
        rows,error=client.get_bars('QQQ','5Min',limit=4)
        self.assertFalse(error)
        self.assertEqual([candle(i) for i in range(8,12)],rows)
        self.assertEqual('desc',calls[0]['sort'])
        self.assertEqual(1,len(calls))
        self.assertIn('start',calls[0])

    def test_short_pages_are_followed_until_requested_recent_count(self):
        client=Reader(); client._get=Mock(side_effect=[
            dict(bars=[candle(5),candle(4)],next_page_token='p2'),
            dict(bars=[candle(3),candle(2)],next_page_token='p3'),
        ])
        rows,error=client.get_bars('QQQ','5Min',limit=4)
        self.assertFalse(error)
        self.assertEqual([candle(i) for i in range(2,6)],rows)
        self.assertEqual('p2',client._get.call_args_list[1].args[1]['page_token'])

    def test_daily_history_also_selects_latest_but_stays_chronological(self):
        client=Reader(); client._get=Mock(return_value=dict(bars=[candle(2),candle(1)]))
        rows,error=client.get_bars('QQQ','Day',limit=2)
        self.assertFalse(error)
        self.assertEqual([candle(1),candle(2)],rows)
        params=client._get.call_args.args[1]
        self.assertEqual('1Day',params['timeframe'])
        self.assertEqual('desc',params['sort'])

    def test_duplicate_page_boundaries_do_not_displace_recent_unique_candles(self):
        client=Reader(); client._get=Mock(side_effect=[
            dict(bars=[candle(4),candle(3)],next_page_token='p2'),
            dict(bars=[candle(3),candle(2)],next_page_token='p3'),
            dict(bars=[candle(1)],next_page_token=None),
        ])
        rows,error=client.get_bars('QQQ','5Min',limit=4)
        self.assertFalse(error)
        self.assertEqual([candle(i) for i in range(1,5)],rows)

    def test_repeated_pagination_token_fails_instead_of_claiming_complete_history(self):
        client=Reader(); client._get=Mock(return_value=dict(bars=[candle(1)],next_page_token='same'))
        rows,error=client.get_bars('QQQ','5Min',limit=10)
        self.assertTrue(error)
        self.assertEqual([],rows)
        self.assertLessEqual(client._get.call_count,2)

    def test_no_available_bars_is_not_api_failure(self):
        client=Reader(); client._get=Mock(return_value={'bars':None})
        self.assertEqual(([],False),client.get_bars('QQQ','5Min'))

    def test_actual_background_worker_gets_recent_history_without_order_permissions(self):
        import pandas as pd
        from trading.loop.research_pass import market_readers, observe_ticker
        client=Reader()
        def endpoint(url,params):
            source=[candle(i) for i in range(2000)]
            if params.get('sort')=='desc':
                source.reverse()
            return dict(bars=source[:params['limit']],next_page_token='more')
        client._get=endpoint
        client.get_session_bars=Mock(return_value=([candle(2001)],False,True))
        client.get_latest_quote=Mock()
        client.is_market_open=Mock(return_value=True)
        market,options=market_readers(client,Mock())
        with ExitStack() as stack:
            for name in ('record_scanner_candles','capture_due_candidate_option_quotes'):
                stack.enter_context(patch('trading.loop.research_pass.'+name))
            stack.enter_context(patch('trading.loop.research_pass.enabled_observation_strategy_ids',return_value={'CTX_1H_SQUEEZE_MACD_LONG'}))
            stack.enter_context(patch('trading.loop.research_pass.reviewed_execution_strategy_ids',return_value=set()))
            stack.enter_context(patch('trading.loop.research_pass.enabled_tested_research_ids',return_value=set()))
            stack.enter_context(patch('trading.loop.research_pass.evaluate_injected_setups',return_value=([],{},None)))
            stack.enter_context(patch('trading.loop.research_pass.load_scanner_candles',return_value=pd.DataFrame()))
            stack.enter_context(patch('trading.loop.research_pass.evaluate_tested_research',return_value=[]))
            route=stack.enter_context(patch('trading.loop.research_pass.route_signals',return_value=[]))
            observe_ticker(market,options,'QQQ',{'shadow_ledger_enabled':True},{},Mock(),4000,lambda:False)
        frame=route.call_args.args[0]
        expected=pd.Timestamp(candle(1999)['t']).tz_convert('America/New_York').tz_localize(None)
        self.assertIn(expected,frame['time'].tolist())
        self.assertEqual(1501,len(frame))
        self.assertEqual(set(),route.call_args.kwargs['enabled_strategies'])
        self.assertFalse(hasattr(market,'place_option_order'))

    def test_invalid_limit_and_malformed_timestamp_fail_closed(self):
        client=Reader(); client._get=Mock(return_value={'bars':[{'t':'not a timestamp'}]})
        self.assertEqual(([],True),client.get_bars('QQQ','5Min',limit=0))
        client._get.assert_not_called()
        self.assertEqual(([],True),client.get_bars('QQQ','5Min',limit=1))


if __name__=='__main__':
    unittest.main()
