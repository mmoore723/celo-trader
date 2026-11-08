from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from strategy_health.underlying_capture import (
    Feed, collect, observation, read_watch, save, watched_trades,
)
from strategy_health.structural_capture import entry_levels

NOW = datetime(2026, 11, 6, 20, 59, 59, tzinfo=timezone.utc)


def row(identity=1, status='open', deadline=None, ticker='SPY'):
    return dict(id=identity, status=status, ticker=ticker,
                strategy_context_json=json.dumps({'exit_deadline': deadline or NOW.isoformat()}))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'paper.db'
        with sqlite3.connect(self.path) as conn:
            conn.execute('''CREATE TABLE trades (id INTEGER, ticker TEXT,status TEXT,
                strategy_context_json TEXT,broker_account_id TEXT,paper INTEGER,entry_time TEXT)''')
            conn.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?)',
                         (1, 'SPY', 'open', row()['strategy_context_json'], 'a', 1, NOW.isoformat()))
            conn.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?)',
                         (2, 'QQQ', 'open', row()['strategy_context_json'], 'b', 1, NOW.isoformat()))
            conn.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?)',
                         (3, 'TSLA', 'open', row()['strategy_context_json'], 'a', 0, NOW.isoformat()))

    def test_restart_reads_durable_positions_and_account_mode(self):
        self.assertEqual(({'SPY': [1]}, []), read_watch(self.path, 'a', True, NOW))
        self.assertEqual(({'SPY': [1]}, []), read_watch(self.path, 'a', True, NOW))
        self.assertEqual(({'TSLA': [3]}, []), read_watch(self.path, 'a', False, NOW))

    def test_closed_trade_stays_through_deadline_and_close_grace(self):
        rows = [row(status='closed')]
        self.assertEqual({'SPY': [1]}, watched_trades(rows, NOW + timedelta(seconds=20))[0])
        self.assertEqual({}, watched_trades(rows, NOW + timedelta(seconds=31))[0])

    def test_missing_deadline_is_explicit_not_invented(self):
        data = row(); data['strategy_context_json'] = '{}'
        self.assertEqual(({'SPY': [1]}, [1]), watched_trades([data], NOW))
        data['status'] = 'closed'
        self.assertEqual(({}, [1]), watched_trades([data], NOW))

    def test_raw_trade_stamp_never_uses_bid_ask_stamp(self):
        out = observation({'last': 100, 'bid_date': NOW.timestamp()*1000}, NOW, [1])
        self.assertIsNone(out[1]); self.assertIn('missing_or_invalid_trade_time', out[7])
        out = observation({'last': 100, 'trade_date': (NOW-timedelta(seconds=60)).timestamp()*1000}, NOW, [1])
        self.assertEqual(60, out[6]); self.assertIn('older_than_two_polls', out[7])

    def test_invalid_and_future_last_are_not_silently_fixed(self):
        out = observation({'last': -1, 'trade_date': (NOW+timedelta(seconds=1)).timestamp()*1000}, NOW, [1])
        self.assertIsNone(out[2]); self.assertIn('trade_time_after_receipt', out[7])
        for value in (None, 0, 'bad', 'nan'):
            self.assertIn('missing_or_invalid_last', observation({'last': value}, NOW, [1])[7])

    def test_save_is_append_only_and_duplicate_idempotent(self):
        quote = {'symbol':'SPY', 'last':100, 'last_volume':25,
                 'trade_date': NOW.timestamp()*1000, 'bid':0, 'ask':0}
        self.assertEqual((1, {}), save(self.path, 'a', True, {'SPY':[1]}, [quote], NOW))
        self.assertEqual((0, {}), save(self.path, 'a', True, {'SPY':[1]}, [quote], NOW))
        save(self.path, 'a', True, {'SPY':[1]}, [quote], NOW+timedelta(seconds=5))
        save(self.path, 'b', True, {'SPY':[2]}, [quote], NOW)
        save(self.path, 'a', False, {'SPY':[3]}, [quote], NOW)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(4, conn.execute('SELECT count(*) FROM underlying_trade_observations').fetchone()[0])
            self.assertEqual(3, conn.execute('SELECT count(*) FROM trades').fetchone()[0])

    def test_missing_quote_recorded_and_close_session_still_collected(self):
        feed = Mock()
        feed.get.side_effect = [({'clock':{'state':'postmarket'}}, NOW), ({'quotes':{}}, NOW)]
        result = collect(self.path, 'a', True, feed, NOW)
        self.assertEqual('degraded', result['status'])
        self.assertIn('SPY', result['quote_problems'])
        self.assertEqual(1, result['rows_saved'])

    def test_closed_market_waits_without_false_forward_success(self):
        feed = Mock(); feed.get.return_value = ({'clock':{'state':'closed'}}, NOW)
        result = collect(self.path, 'a', True, feed, NOW)
        self.assertEqual('waiting_for_market', result['status'])
        self.assertNotIn('last_collection_at', result)
        self.assertEqual(1, feed.get.call_count)

    def test_clock_failure_not_misrepresented_as_closed(self):
        feed = Mock(); feed.get.return_value = ({}, NOW)
        with self.assertRaisesRegex(ValueError, 'unavailable_market_clock'):
            collect(self.path, 'a', True, feed, NOW)

    def test_feed_is_get_only_no_redirect_or_execution_endpoint(self):
        with self.assertRaises(ValueError): Feed('')
        feed = Feed('fake-token')
        with self.assertRaises(ValueError): feed.get('/accounts/a/orders')
        with patch('strategy_health.underlying_capture.requests.get') as get:
            get.return_value.json.return_value = {'clock':{'state':'open'}}
            feed.get('/markets/clock')
            self.assertEqual(False, get.call_args.kwargs['allow_redirects'])
            self.assertEqual((2,5), get.call_args.kwargs['timeout'])

    def test_timeout_propagates_without_any_observation(self):
        feed = Mock(); feed.get.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError): collect(self.path, 'a', True, feed, NOW)
        with sqlite3.connect(self.path) as conn:
            self.assertFalse(conn.execute("SELECT name FROM sqlite_master WHERE name='underlying_trade_observations'").fetchone())

    def test_rate_limit_health_and_bounded_retry_delay(self):
        import requests
        from strategy_health.underlying_capture import main
        response = requests.Response(); response.status_code = 429
        response.headers['Retry-After'] = '120'
        with patch('sys.argv', ['capture','--user','test','--once']), \
             patch('config.get_settings', return_value={'active_broker_account_id':'a','paper_trading':True}), \
             patch('config.get_api_keys', return_value={'tradier_market_api_key':'test'}), \
             patch('config.get_db_path', return_value=self.path), \
             patch('config.get_user_data_dir', return_value=Path(self.temp.name)), \
             patch('auth.context.set_current_user'), \
             patch('strategy_health.underlying_capture.collect', side_effect=requests.HTTPError(response=response)), \
             patch('builtins.print'):
            main()
        health = json.loads((Path(self.temp.name)/'underlying_capture_health.json').read_text())
        self.assertEqual('blocked',health['status'])
        self.assertEqual(120,health['poll_seconds'])
        self.assertIsNone(health['last_successful_collection_at'])


class LevelTests(unittest.TestCase):
    def test_raw_touch_and_extreme_are_metadata_only(self):
        bars = [SimpleNamespace(timestamp=NOW-timedelta(minutes=5), low=90, high=110),
                SimpleNamespace(timestamp=NOW, low=95, high=105)]
        for side, key, expected in [('long','support',90), ('short','resistance',110)]:
            candidate = SimpleNamespace(side=SimpleNamespace(value=side),timestamp=NOW,stop=85)
            out = entry_levels('V2_VWAP_PULLBACK', candidate, bars, None, 5)['structural_levels']
            self.assertEqual(expected, out[key]); self.assertEqual(85,candidate.stop)
            self.assertEqual('captured',out['status'])
            out = entry_levels('V2_IMPULSE_ANCHORED_VWAP_PULLBACK',candidate,bars,
                               SimpleNamespace(_pullback_extreme=92),5)['structural_levels']
            self.assertEqual(92,out[key]); self.assertFalse(out['updates_after_entry'])

    def test_missing_level_and_old_signal_do_not_get_fake_stop(self):
        candidate=SimpleNamespace(side=SimpleNamespace(value='long'),timestamp=NOW,stop=85)
        bars=[SimpleNamespace(timestamp=NOW,low=90,high=110)]
        out=entry_levels('V2_IMPULSE_ANCHORED_VWAP_PULLBACK',candidate,bars,
                         SimpleNamespace(_pullback_extreme=None),5)
        self.assertEqual('missing',out['structural_levels']['status'])
        candidate.timestamp=NOW-timedelta(minutes=5)
        out=entry_levels('V2_VWAP_PULLBACK',candidate,bars,None,5)
        self.assertEqual('missing',out['structural_levels']['status'])
        self.assertEqual({},entry_levels('OTHER',candidate,bars,None,5))
