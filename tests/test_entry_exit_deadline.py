import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from trading.entry.exit_deadline import capture_policy, freeze_at_fill
from tests.test_exit_outage_preflight import PAIRS

NOW = datetime.fromisoformat('2026-11-02T10:00:00-05:00')


class EntryDeadlineTests(unittest.TestCase):
    def test_five_complete_trades_do_not_mean_tuning_evidence(self):
        from tests.test_weekly_exit_audit import trade
        from strategy_health.weekly_exit_audit.engine import audit
        result = audit([trade(i) for i in range(5)])
        self.assertEqual('COMPLETE', result['status'])
        self.assertEqual('KEEP BASELINE', result['recommendation'])
        self.assertFalse(result['sample_evidence']['sufficient'])
        self.assertEqual(3, result['sample_evidence']['train_count'])
        self.assertEqual(2, result['sample_evidence']['test_count'])
        self.assertIn('replay coverage only', result['reason'])

    def test_all_fifteen_pairs_capture_actual_policy_at_fill(self):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        for ticker, strategy in PAIRS:
            for close_hour in (13, 16):
                with self.subTest(ticker=ticker, strategy=strategy, close_hour=close_hour):
                    close = NOW.replace(hour=close_hour)
                    with patch('trading.research_session_clock.session_close_if_open', return_value=close):
                        plan = capture_policy(strategy, Mock(), NOW)
                    filled = NOW + timedelta(minutes=2)
                    context = freeze_at_fill(json.dumps(plan), filled.isoformat())
                    hold = 30 if strategy == 'RESEARCH_FAILED_RANGE_V2' else REVIEWED_STRATEGIES[strategy].exit_minutes
                    expected = close - timedelta(minutes=5)
                    if hold is not None:
                        expected = min(expected, filled + timedelta(minutes=hold))
                    self.assertEqual(expected, datetime.fromisoformat(context['exit_deadline']))
                    self.assertEqual('captured', context['exit_deadline_capture']['status'])
                    self.assertEqual(context, freeze_at_fill(context, (filled + timedelta(minutes=20)).isoformat()))

    def test_missing_session_and_historical_rows_are_not_fabricated(self):
        with patch('trading.research_session_clock.session_close_if_open', return_value=None):
            plan = capture_policy('V2_SPY_TREND_CONT', Mock(), NOW)
        self.assertNotIn('exit_deadline', freeze_at_fill(plan, NOW.isoformat()))
        historic = {'strategy_version': '2.1.0', 'max_hold_minutes': 30}
        self.assertEqual(historic, freeze_at_fill(historic, NOW.isoformat()))

    def test_invalid_fill_clock_does_not_claim_coverage(self):
        with patch('trading.research_session_clock.session_close_if_open', return_value=NOW.replace(hour=13)):
            plan = capture_policy('V2_ORB_PULLBACK', Mock(), NOW)
        for stamp in ('2026-11-02T10:00:00', 'bad', '2026-11-02T14:00:00-05:00'):
            context = freeze_at_fill(plan, stamp)
            self.assertNotIn('exit_deadline', context)
            self.assertEqual('invalid_fill_clock', context['exit_deadline_capture']['status'])

    def test_durable_fill_freezes_deadline_and_preserves_it_on_partial_top_up(self):
        from tests.test_execution_recovery import RecoveryTests
        fixture = RecoveryTests()
        fixture.setUp()
        try:
            context = fixture.context()
            # This fixture's confirmed fill is Sep 3 at 14:00 ET.
            now = datetime.fromisoformat('2026-09-03T13:59:00-04:00')
            with patch('trading.research_session_clock.session_close_if_open', return_value=now.replace(hour=16, minute=0)):
                plan = capture_policy('V2_SPY_TREND_CONT', fixture.client, now)
            context['entry_record']['strategy_context_json'] = json.dumps(plan)
            fixture.next_status, fixture.next_qty = 'pending_cancel', '1'
            fixture.enter(context)
            row = fixture.rows()[0]
            saved = json.loads(row['strategy_context_json'])
            self.assertEqual('2026-09-03T14:30:00-04:00', saved['exit_deadline'])
            fixture.orders['order-1'].update(status='filled', filled_qty='3', filled_at='2026-09-03T18:05:00Z')
            from broker.recovery import reconcile_orders
            reconcile_orders(fixture.make_client())
            updated = fixture.rows()[0]
            self.assertEqual(3, updated['contracts'])
            self.assertEqual(saved, json.loads(updated['strategy_context_json']))
        finally:
            fixture.doCleanups()
