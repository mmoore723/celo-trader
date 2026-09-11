"""Every registered exit exercised with real evaluators through the study worker.

These are deterministic integration fixtures, not live profitability evidence.
They enroll from candidate rows, read UTC broker-format bars and persist the exit.
"""
from datetime import datetime, timedelta
from importlib import import_module
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from auth.context import get_current_user_id
from config.research_snapshot import research_settings_snapshot
from database import expiration_study as ledger
from strategy_health.expiration_study_exits import PROTOCOL_BY_STRATEGY, TIMED, normalized_profit
from tests import test_authored_exit_capture as base
from tests.test_expiration_study_selection import Clock, Reader
from trading import expiration_study as worker


FIXTURES = (
    ('trend', 'TrendExitCaptureTests'), ('vwap', 'VwapExitCaptureTests'),
    ('fvg', 'FvgExitCaptureTests'), ('orb', 'OrbExitCaptureTests'),
    ('turtle', 'TurtleExitCaptureTests'), ('reversion', 'ReversionExitCaptureTests'),
    ('compression', 'CompressionExitCaptureTests'), ('range_sweep', 'RangeSweepExitCaptureTests'),
    ('afternoon', 'AfternoonExitCaptureTests'), ('midday', 'MiddayExitCaptureTests'),
    ('ema', 'EmaExitCaptureTests'), ('rsi_macd', 'RsiMacdExitCaptureTests'),
    ('gap_fill', 'GapFillExitCaptureTests'), ('context_vwap', 'ContextVwapCaptureTests'),
    ('displacement', 'DisplacementExitCaptureTests'), ('context_orb', 'ContextOrbExitCaptureTests'),
    ('atr10', 'Atr10ExitCaptureTests'), ('squeeze', 'SqueezeExitCaptureTests'),
)


class AllProtocolIntegrationTests(unittest.TestCase):
    def exercise(self, case, *, special=None, timer=None):
        f = getattr(case, 'f', case)
        if special in {'supertrend', 'momentum'}:
            module = import_module('strategy_health.'+special+'_exit')
            state = import_module('tests.test_'+special+'_exit_measurement').seed()
            f.seed('study', strategy_id=module.STRATEGY_ID, protocol=module.PROTOCOL, state=state)
            if special == 'supertrend':
                f.frame.loc[5:9, ['low', 'close']] = [96, 97]
        elif timer:
            f.seed('study', strategy_id=timer, protocol=None)
        else:
            case.seed('study')
        if special == 'ema_native':
            from trading.research_ema_history import NATIVE_POLICY
            with f.connect() as conn:
                meta = json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id="study"').fetchone()[0])
                meta['history_policy'] = NATIVE_POLICY
                conn.execute('UPDATE shadow_candidates SET metadata_json=? WHERE candidate_id="study"', (json.dumps(meta),))
            f.frame = f.frame.iloc[[0, 15]].copy()
            f.frame.loc[15, 'low'] = 97
        with f.connect() as conn:
            candidate = dict(conn.execute('SELECT * FROM shadow_candidates WHERE candidate_id="study"').fetchone())
            primary_before = {name: [tuple(r) for r in conn.execute('SELECT * FROM '+name)]
                              for name in ('shadow_candidates', 'candidate_option_quote_observations',
                                           'research_strategy_exits')}
        sid = candidate['strategy_id']
        clock = Clock()
        clock.now = datetime.fromisoformat(candidate['observed_at'])+timedelta(seconds=2)
        entry_time = clock.now
        source = Reader(clock)
        bullish = candidate['direction'] == 'bullish'
        symbol = 'META260918C00101000' if bullish else 'META260918P00099000'
        source.chain[0].update(symbol=symbol, strike=101 if bullish else 99)
        source.quote.update(symbol=symbol, source_symbol=symbol,
                            bid_date=entry_time.isoformat(), ask_date=entry_time.isoformat())
        reader = worker.SharedReads(source, clock)
        signal = SimpleNamespace(strategy_id=sid, direction=candidate['direction'],
                                 meta={'shadow_candidate_id': 'study'})
        settings = dict(active_broker_account_id='a', paper_trading=True, broker_provider='alpaca')
        market, options = Mock(), Mock()
        values = [dict(t=row.time.tz_localize('America/New_York').tz_convert('UTC').isoformat(),
                       o=row.open, h=row.high, l=row.low, c=row.close, v=getattr(row, 'volume', 100))
                  for row in f.frame.itertuples()]
        market.get_session_bars.return_value = values, None, None
        if special == 'ema_native':
            market.get_bars.return_value = values, None
        with patch.object(worker, 'get_conn', f.connect), research_settings_snapshot(get_current_user_id(), settings):
            worker.observe(signal=signal, ticker='META', price=100, reader=reader,
                           settings=settings, clock=clock)
            with f.connect() as conn:
                self.assertEqual('collecting', ledger.load(conn, account='a')[0]['state']['status'])
            ticks = [(f.now, dict(f.quote.return_value))]
            if special == 'gap_fill':
                ticks.append((datetime(2026, 9, 10, 10, 21), dict(bid=.8, ask=.9, bid_date='2026-09-10T10:21:00')))
            if special in {'context_orb', 'atr10'}:
                ticks.append((datetime(2026, 9, 10, 10, 8), dict(bid=4, ask=4.1, bid_date='2026-09-10T10:07:30')))
            if special == 'squeeze':
                ticks.append((datetime(2026, 9, 10, 10, 33), dict(bid=5, ask=5.1, bid_date='2026-09-10T10:32:30')))
            if timer:
                at = entry_time+timedelta(minutes=TIMED[timer])
                ticks = [(at, dict(bid=1.2, ask=1.3, bid_date=at.isoformat()))]
            for now, quote in ticks:
                clock.now = now
                options.get_option_quote.return_value = {**quote, 'symbol': symbol, 'source_symbol': symbol}
                stats = worker.capture(market=market, options=options, settings=settings, worker_state={},
                                       stopped=lambda: False, clock=clock)
                self.assertEqual(0, stats['failed_rows'], sid)
            with f.connect() as conn:
                state = ledger.load(conn, account='a')[0]['state']
                for table, before in primary_before.items():
                    self.assertEqual(before, [tuple(r) for r in conn.execute('SELECT * FROM '+table)], (sid, table))
            self.assertEqual('priced', state['status'], (sid, state))
            self.assertIsNotNone(normalized_profit(state), sid)
            self.assertEqual(PROTOCOL_BY_STRATEGY[sid], state['protocol'])
            self.assertEqual(symbol, state['contract_symbol'])
            self.assertTrue(all(call.args == (symbol,) for call in options.get_option_quote.call_args_list))
            if timer:
                self.assertEqual('fixed_'+str(TIMED[timer])+'m', state['reason'])
                market.get_session_bars.assert_not_called()
            if special == 'ema_native':
                market.get_session_bars.assert_not_called()
                market.get_bars.assert_called_once_with('META', '15Min', limit=500)
                self.assertEqual('underlying_stop', state['reason'])
            if special in {'context_orb', 'atr10'}:
                self.assertAlmostEqual(126.7, normalized_profit(state))
            if special == 'squeeze':
                self.assertAlmostEqual(296.7, normalized_profit(state))
            # A new polling invocation cannot overwrite a terminal result.
            worker.capture(market=market, options=options, settings=settings, worker_state={},
                           stopped=lambda: False, clock=clock)
            with f.connect() as conn:
                self.assertEqual(state, ledger.load(conn, account='a')[0]['state'])
        return sid

    def test_all_26_registered_strategies_have_real_worker_exit_results(self):
        seen = set()
        for name in ('impulse', 'supertrend', 'momentum'):
            with self.subTest(strategy=name):
                case = base.AuthoredExitCaptureTests()
                case.setUp()
                try:
                    seen.add(self.exercise(case, special=name))
                finally:
                    case.doCleanups()
        for name, class_name in FIXTURES:
            with self.subTest(strategy=name):
                case = getattr(import_module('tests.test_'+name+'_exit_capture'), class_name)()
                case.setUp()
                try:
                    seen.add(self.exercise(case, special=name))
                finally:
                    case.doCleanups()
        for sid in TIMED:
            with self.subTest(strategy=sid):
                case = base.AuthoredExitCaptureTests()
                case.setUp()
                try:
                    seen.add(self.exercise(case, timer=sid))
                finally:
                    case.doCleanups()
        self.assertEqual(set(PROTOCOL_BY_STRATEGY), seen)
        self.assertEqual(26, len(seen))

    def test_current_native_ema_uses_real_fifteen_minute_reader(self):
        case = import_module('tests.test_ema_exit_capture').EmaExitCaptureTests()
        case.setUp()
        try:
            self.exercise(case, special='ema_native')
        finally:
            case.doCleanups()


if __name__ == '__main__':
    unittest.main()
