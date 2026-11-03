import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import ExitStack

from risk.daily_override import effective_limits, save_override, session_date, override_path
from risk.halt_controls import resume_after_review
from risk.manager import RiskManager


class DailyOverrideTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "paper.json"
        self.scope = self.stack.enter_context(patch("risk.daily_override._lock_path", return_value=self.path))
        self.settings = {"daily_loss_hard_cap_pct": 30, "max_daily_loss_pct": .1}
        self.stack.enter_context(patch("database.get_open_trades", return_value=[]))
        self.stack.enter_context(patch("database.log_event"))
        self.stack.enter_context(patch("risk.halt_controls.flatten_pending", return_value=False))
        self.clear = self.stack.enter_context(patch("risk.halt_controls.clear_kill_lock"))
        self.lock = self.stack.enter_context(patch("risk.halt_controls.check_kill_lock", side_effect=[(True, "halt"), (False, None)]))
        self.broker = Mock()
        self.broker.get_positions.return_value = []
        self.broker.get_open_orders.return_value = []
        self.broker.get_account.return_value = {"equity": 1700}

    def resume(self, limit=400, session=None):
        return resume_after_review(self.broker, day_start=2000, settings=self.settings,
            realized=-300, temporary_limit_usd=limit, session=session or session_date())

    def test_explicit_override_persists_and_does_not_change_settings(self):
        self.resume()
        self.clear.assert_called_once()
        self.assertEqual(effective_limits(2000, .3, .1), (.2, .2))
        self.assertEqual(json.loads(override_path().read_text())["limit_usd"], 400)
        self.assertEqual(self.settings, {"daily_loss_hard_cap_pct": 30, "max_daily_loss_pct": .1})

    def test_existing_losses_are_not_reset(self):
        with self.assertRaisesRegex(ValueError, "still breached"):
            self.resume(300)
        self.clear.assert_not_called()
        self.assertFalse(override_path().exists())

    def test_invalid_limits(self):
        for limit in (0, -1, 2001, float("nan"), float("inf"), True):
            with self.subTest(limit=limit):
                self.lock.side_effect = [(True, "halt")]
                with self.assertRaises(ValueError):
                    self.resume(limit)
        self.clear.assert_not_called()

    def test_stale_session_rejected(self):
        with self.assertRaisesRegex(ValueError, "date changed"):
            self.resume(session="2000-01-01")
        self.clear.assert_not_called()

    def test_expiry_and_account_isolation(self):
        save_override(400, 2000, session_date())
        with patch("risk.daily_override.session_date", return_value="2099-01-01"):
            self.assertEqual(effective_limits(2000, .3, .1), (.3, .1))
        self.scope.return_value = self.path.with_name("live.json")
        self.assertEqual(effective_limits(2000, .3, .1), (.3, .1))

    def test_changed_day_open_blocks(self):
        save_override(400, 2000, session_date())
        with self.assertRaisesRegex(ValueError, "day-open"):
            effective_limits(2100, .3, .1)

    def test_write_failure_never_unlocks(self):
        with patch("risk.daily_override.atomic_write_json", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                self.resume()
        self.clear.assert_not_called()

    def test_broker_pending_orders_still_block(self):
        self.broker.get_open_orders.return_value = [{"id": "pending"}]
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.resume()
        self.assertFalse(override_path().exists())

    def test_guard_uses_new_limit_and_rehalts_at_boundary(self):
        save_override(400, 2000, session_date())
        with patch("risk.guard.get_settings", return_value=self.settings), \
             patch("trading.state.get_user_state", return_value={"day_start_balance": 2000}), \
             patch("risk.guard.check_kill_lock", return_value=(False, None)), \
             patch("risk.guard.get_todays_realized_pnl", return_value=-300) as pnl, \
             patch("risk.guard.set_kill_lock") as halt, \
             patch("risk.guard.log_event"), patch("alerts.send_alert"):
            risk = RiskManager(1700)
            self.assertIsNone(risk.check_daily_loss(1700))
            pnl.return_value = -400
            self.assertIsNotNone(risk.check_daily_loss(1600))
            halt.assert_called_once()
