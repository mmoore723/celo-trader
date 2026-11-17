import unittest
from unittest.mock import patch
from trading.diagnostics.entry_checks import capture_checks, record_checks

class CaptureTests(unittest.TestCase):
    def test_isolated_and_latest_only(self):
        with patch('trading.diagnostics.entry_checks.logging.getLogger') as logger:
            with capture_checks('trend','QQQ'):
                record_checks([{'name':'old','passed':True}])
                record_checks([{'name':'Range break','status':'pending','reason':'Waiting for $50'}])
            data=logger.return_value.info.call_args.kwargs['extra']
            self.assertEqual(data['ticker'],'QQQ')
            self.assertEqual(data['checks'][0]['name'],'Range break')
            logger.reset_mock()
            record_checks([{'name':'outside','passed':True}])
            with capture_checks('other','SPY'): pass
            logger.assert_not_called()
    def test_quiet_and_cleared_checks_are_not_emitted(self):
        with patch('trading.diagnostics.entry_checks.logging.getLogger') as logger:
            with capture_checks('trend','QQQ',enabled=False):
                record_checks([{'name':'EMA','passed':True}])
            with capture_checks('trend','QQQ'):
                record_checks([{'name':'historic','passed':True}])
                record_checks([])
            logger.assert_not_called()
    def test_logging_failure_does_not_interrupt(self):
        with patch('trading.diagnostics.entry_checks.logging.getLogger',side_effect=RuntimeError):
            with capture_checks('trend','QQQ'):
                record_checks([{'name':'EMA','passed':True}])

    def test_exception_does_not_publish_partial_pass(self):
        with patch('trading.diagnostics.entry_checks.logging.getLogger') as logger:
            with self.assertRaises(RuntimeError):
                with capture_checks('trend','QQQ'):
                    record_checks([{'name':'EMA','passed':True}])
                    raise RuntimeError('evaluation failed')
            logger.assert_not_called()

    def test_vwap_diagnostics_match_actual_candidate_and_do_not_mutate_engine(self):
        from datetime import datetime, timedelta
        from research.engine.models import Bar
        from research.engine.strategies.vwap_pullback import VWAPPullback
        from trading.diagnostics.entry_checks import library_checks
        from copy import deepcopy
        # Several price paths exercise passing and failing branches without broker calls.
        import random
        rng = random.Random(17)
        for sample in range(80):
            price = 100.
            bars = []
            for i in range(25):
                opening = price
                price += rng.uniform(-.3,.3)
                bars.append(Bar(datetime(2026,11,17,9,30)+timedelta(minutes=i*5), opening,
                                max(opening,price)+.08,min(opening,price)-.08,price,1000))
            engine = VWAPPullback()
            before = deepcopy(engine.__dict__)
            expected = engine.evaluate(bars)
            with patch('trading.diagnostics.entry_checks.logging.getLogger') as logger:
                with capture_checks('V2_VWAP_PULLBACK','AMZN'):
                    library_checks(engine,bars)
                checks = logger.return_value.info.call_args.kwargs['extra']['checks']
            self.assertEqual(all(c.get('passed') for c in checks), expected is not None)
            self.assertEqual(engine.__dict__,before)
