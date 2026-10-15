from contextlib import ExitStack
from unittest.mock import Mock, patch
import unittest

from risk.manager import RiskManager


class EquityBreachConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("risk.guard.get_settings", return_value={
            "daily_loss_hard_cap_pct": 30, "max_daily_loss_pct": .1}))
        self.stack.enter_context(patch("trading.state.get_user_state", return_value={"day_start_balance": 3215.8}))
        self.realized = self.stack.enter_context(patch("risk.guard.get_todays_realized_pnl", return_value=-150))
        self.locked = self.stack.enter_context(patch("risk.guard.check_kill_lock", return_value=(False,None)))
        self.persist = self.stack.enter_context(patch("risk.guard.set_kill_lock"))
        self.stack.enter_context(patch("risk.guard.log_event"))
        self.reader = Mock(return_value={"equity":2380.68})
        self.risk = RiskManager(2380.68, equity_reader=self.reader)

    def test_transient_opening_breach_does_not_create_a_day_lock(self):
        self.assertIsNone(self.risk.check_daily_loss(2095.8))
        self.reader.assert_called_once_with()
        self.persist.assert_not_called()

    def test_confirmed_breach_still_halts_at_same_threshold(self):
        self.reader.return_value={"equity":2095.8}
        self.assertIn("equity down $1120.00",self.risk.check_daily_loss(2095.8))
        self.persist.assert_called_once_with()

    def test_realized_hard_breach_never_waits_for_confirmation(self):
        self.realized.return_value=-1000
        self.assertIsNotNone(self.risk.check_daily_loss(2380.68))
        self.reader.assert_not_called()
        self.persist.assert_called_once_with()

    def test_realized_soft_breach_still_halts(self):
        self.realized.return_value=-400
        self.assertIsNotNone(self.risk.check_daily_loss(2380.68))
        self.reader.assert_not_called()
        self.assertEqual(self.persist.call_args.kwargs["reason"],"daily_loss_soft_cap")

    def test_normal_balance_does_not_add_network_reads(self):
        self.assertIsNone(self.risk.check_daily_loss(2380.68))
        self.reader.assert_not_called()

    def test_existing_halt_is_not_automatically_cleared(self):
        self.locked.return_value=(True,"existing halt")
        self.assertEqual(self.risk.check_daily_loss(2380.68),"existing halt")
        self.reader.assert_not_called()

    def test_missing_or_invalid_confirmation_retains_protection(self):
        for response in ({}, {"equity":float("nan")}, {"equity":-1}, {"equity":float("inf")}):
            with self.subTest(response=response):
                self.reader.return_value=response
                self.persist.reset_mock()
                self.assertIsNotNone(self.risk.check_daily_loss(2095.8))
                self.persist.assert_called_once()

    def test_network_failure_retains_protection(self):
        self.reader.side_effect=RuntimeError("offline")
        self.assertIsNotNone(self.risk.check_daily_loss(2095.8))
        self.persist.assert_called_once()

    def test_zero_equity_is_a_valid_confirmed_breach(self):
        self.reader.return_value={"equity":0}
        self.assertIsNotNone(self.risk.check_daily_loss(2095.8))
        self.persist.assert_called_once()
