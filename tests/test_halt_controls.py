from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from risk.halt_controls import halt_status, resume_after_review


class HaltControlsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.lock = self.stack.enter_context(patch("risk.halt_controls.check_kill_lock", side_effect=[(True, "halt"), (False, None)]))
        self.pending = self.stack.enter_context(patch("risk.halt_controls.flatten_pending", return_value=False))
        self.clear = self.stack.enter_context(patch("risk.halt_controls.clear_kill_lock"))
        self.journal = self.stack.enter_context(patch("database.get_open_trades", return_value=[]))
        self.stack.enter_context(patch("database.log_event"))
        self.broker = Mock()
        self.broker.get_positions.return_value = []
        self.broker.get_open_orders.return_value = []
        self.broker.get_account.return_value = {"equity": 2380.68}
        self.settings = {"daily_loss_hard_cap_pct": 30, "max_daily_loss_pct": .1}
        self.stack.enter_context(patch("risk.halt_controls._lock_path", return_value=Path("paper-scope.json")))

    def resume(self, **kwargs):
        resume_after_review(self.broker, day_start=3215.8, settings=self.settings,
                            realized=kwargs.get("realized", -150))

    def test_recovered_equity_allows_explicit_resume_without_limit_change(self):
        self.resume()
        self.clear.assert_called_once_with()
        self.assertEqual(self.settings, {"daily_loss_hard_cap_pct": 30, "max_daily_loss_pct": .1})

    def test_current_breach_cannot_be_silently_overridden(self):
        self.broker.get_account.return_value = {"equity": 2095.8}
        with self.assertRaisesRegex(ValueError, "still breached"):
            self.resume()
        self.clear.assert_not_called()

    def test_realized_limit_still_applies(self):
        with self.assertRaisesRegex(ValueError, "still breached"):
            self.resume(realized=-400)
        self.clear.assert_not_called()

    def test_pending_flatten_blocks_resume(self):
        self.pending.return_value = True
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.resume()
        self.clear.assert_not_called()

    def test_open_broker_position_blocks_resume(self):
        self.broker.get_positions.return_value = [{"qty": "1"}]
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.resume()
        self.clear.assert_not_called()

    def test_open_order_blocks_resume(self):
        self.broker.get_open_orders.return_value = [{"id": "working"}]
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.resume()
        self.clear.assert_not_called()

    def test_unavailable_broker_does_not_unlock(self):
        self.broker.get_account.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            self.resume()
        self.clear.assert_not_called()

    def test_invalid_equity_does_not_unlock(self):
        self.broker.get_account.return_value = {"equity": float("nan")}
        with self.assertRaises(ValueError):
            self.resume()
        self.clear.assert_not_called()

    def test_status_read_failure_is_not_reported_as_trading(self):
        self.pending.side_effect = ValueError("unreadable")
        self.assertEqual(halt_status(), {"halted": True, "reason": "halt", "close_pending": True, "scope": "paper-scope.json"})

    def test_endpoint_requires_authenticated_user(self):
        from fastapi import HTTPException
        from api.routes.bot import get_halt, resume_halt
        for endpoint in (get_halt, resume_halt):
            with self.assertRaises(HTTPException) as raised:
                request = SimpleNamespace(state=SimpleNamespace())
                endpoint(request, {}) if endpoint is resume_halt else endpoint(request)
            self.assertEqual(raised.exception.status_code, 401)

    def test_resume_rejects_another_account_or_mode(self):
        from fastapi import HTTPException
        from api.routes.bot import resume_halt
        with self.assertRaises(HTTPException) as raised:
            resume_halt(SimpleNamespace(state=SimpleNamespace(user_id="admin")), {"scope": "live-scope.json"})
        self.assertEqual(raised.exception.status_code, 409)
        self.clear.assert_not_called()
