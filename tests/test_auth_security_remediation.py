from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


if "bcrypt" not in sys.modules:
    fake_bcrypt = types.ModuleType("bcrypt")
    fake_bcrypt.gensalt = lambda: b"test-salt"
    fake_bcrypt.hashpw = lambda value, salt: b"sha256$" + hashlib.sha256(value).hexdigest().encode()
    fake_bcrypt.checkpw = lambda value, hashed: (
        hashed == b"sha256$" + hashlib.sha256(value).hexdigest().encode()
    )
    sys.modules["bcrypt"] = fake_bcrypt

import auth.users as users
from auth.security import LoginAttemptGuard, origin_is_trusted


PASSWORD = "StrongAudit1!"


class AuthSecurityRemediationTests(unittest.TestCase):
    def test_fresh_login_restores_terms_from_server_not_browser_cache(self):
        from api.routes.auth import _issue_session
        from fastapi import Response
        user = {'user_id': 'one', 'username': 'one', 'is_admin': False, 'session_version': 1}
        with patch('api.routes.auth.jwt_secret', return_value='test-only-signing-secret-at-least-32-characters'):
            for version, expected in [(None, False), ('outdated', False), (users.CURRENT_TERMS_VERSION, True)]:
                result = _issue_session(Response(), {**user, 'terms_version': version}, False)
                self.assertEqual(expected, result['terms_accepted'])
                self.assertEqual('one', result['user_id'])

    def test_password_authentication_returns_persisted_terms_version(self):
        users.get_db().close()
        admin = users.authenticate('admin', PASSWORD)
        self.assertIsNone(admin['terms_version'])
        self.assertTrue(users.accept_terms(admin['user_id']))
        signed_in_again = users.authenticate('admin', PASSWORD)
        self.assertEqual(users.CURRENT_TERMS_VERSION, signed_in_again['terms_version'])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "user_data" / "users.db"
        self.data_path = root / "user_data"
        self.paths = patch.multiple(users, _DB_PATH=self.db_path, _DATA=self.data_path, _ROOT=root)
        self.paths.start()
        self.env = patch.dict(os.environ, {
            "DASHBOARD_PASSWORD": PASSWORD,
            "DASHBOARD_PASSWORD_HASH": "",
            "CELO_ENV": "development",
        }, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.paths.stop()
        self.tmp.cleanup()

    def test_admin_bootstrap_refuses_known_implicit_password(self) -> None:
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "", "DASHBOARD_PASSWORD_HASH": ""}):
            with self.assertRaises(RuntimeError):
                users.get_db()

    def test_password_reset_revokes_existing_session_version(self) -> None:
        users.get_db().close()
        before = users.get_user("admin")
        self.assertEqual(before["session_version"], 1)
        self.assertTrue(users.reset_password("admin", "AnotherStrong2!"))
        after = users.get_user("admin")
        self.assertEqual(after["session_version"], 2)

    def test_invite_is_consumed_atomically(self) -> None:
        users.get_db().close()
        token = users.create_invite("admin", hours=1)
        created = users.create_user_from_invite(token, "audit.user", PASSWORD)
        self.assertEqual(created["username"], "audit.user")
        with self.assertRaisesRegex(ValueError, "Invalid or expired"):
            users.create_user_from_invite(token, "second.user", PASSWORD)

    def test_username_and_bcrypt_length_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            users.normalize_username("bad user")
        with self.assertRaisesRegex(ValueError, "72 UTF-8 bytes"):
            users.validate_password("A1!" + "x" * 70)

    def test_origin_policy_rejects_http_production_origin(self) -> None:
        self.assertTrue(origin_is_trusted("https://celotrader.com/settings"))
        self.assertFalse(origin_is_trusted("http://celotrader.com/settings"))
        self.assertFalse(origin_is_trusted("https://evil.example/"))

    def test_login_guard_blocks_and_clears(self) -> None:
        guard = LoginAttemptGuard(max_failures=2, window_seconds=60)
        guard.failure("client:user")
        self.assertFalse(guard.blocked("client:user"))
        guard.failure("client:user")
        self.assertTrue(guard.blocked("client:user"))
        guard.success("client:user")
        self.assertFalse(guard.blocked("client:user"))


if __name__ == "__main__":
    unittest.main()
