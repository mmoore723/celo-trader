"""Historical visibility is not execution authority or a new PF claim."""
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.strategy_inventory import tested_strategy_inventory
from scripts.build_strategy_inventory import build, walk


class StrategyInventoryTests(unittest.TestCase):
    def test_legacy_names_and_uppercase_study_ids_are_not_omitted(self):
        found = {}
        walk({"strategy": "vwap_pullback", "ticker": "TSLA"}, set(), found)
        walk({"study": "CMF_TREND_PULLBACK_V1", "tickers": {"SPY": {"decision": "reject"}, "QQQ": {}}}, set(), found)
        self.assertEqual({"TSLA"}, found["VWAP_PULLBACK"])
        self.assertEqual({"SPY", "QQQ"}, found["CMF_TREND_PULLBACK_V1"])

    def test_matrix_keeps_exact_strategy_ticker_pairs(self):
        found = {}
        walk([{"strategy_id": "CTX_A", "ticker": "TSLA"}, {"strategy_id": "CTX_B", "ticker": "SPY"}], set(), found)
        self.assertEqual({"CTX_A": {"TSLA"}, "CTX_B": {"SPY"}}, found)

    def test_every_report_is_retained_and_invalid_tests_are_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "research/reports/nested"
            reports.mkdir(parents=True)
            (reports / "old.json").write_text(json.dumps({"purpose": "An old test without an ID", "profit_factor": 8}))
            (reports / "invalid.json").write_text(json.dumps({"strategy_id": "OLD_TEST", "profit_factor": 12, "valid": False}))
            result = build(root)
            self.assertEqual(2, result["reports_scanned"])
            self.assertEqual(["research/reports/nested/old.json"], result["other_studies"])
            self.assertEqual("invalid_or_superseded", result["report_details"]["research/reports/nested/invalid.json"]["status"])
            self.assertNotIn("profit_factor", json.dumps(result))
            self.assertNotIn("enabled", json.dumps(result))

    def test_missing_and_malformed_inventory_show_unavailable_not_empty_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            with patch("config.strategy_inventory.INVENTORY_PATH", path):
                self.assertTrue(tested_strategy_inventory()["unavailable"])
                for value in ([], {"strategies": None}, {"strategies": [{}], "report_details": {}, "other_studies": []}):
                    path.write_text(json.dumps(value))
                    self.assertTrue(tested_strategy_inventory()["unavailable"])

    def test_published_inventory_accounts_for_every_report(self):
        payload = tested_strategy_inventory()
        self.assertFalse(payload.get("unavailable"))
        represented = set(payload["other_studies"])
        for row in payload["strategies"]:
            self.assertEqual(len(row["reports"]), row["report_count"])
            represented.update(row["reports"])
        self.assertEqual(set(payload["report_details"]), represented)
        self.assertEqual(payload["reports_scanned"], len(represented))
        self.assertEqual([], payload["unreadable_reports"])

    def test_runnable_research_is_separate_from_saved_reports(self):
        payload = tested_strategy_inventory({"research_strategy_ids": ["V2_TREND_CONT"]})
        runtime = {row["strategy_id"]: row for row in payload["runtime_research"]}
        self.assertTrue(runtime["V2_TREND_CONT"]["enabled"])
        self.assertFalse(runtime["V2_VWAP_PULLBACK"]["enabled"])
        self.assertEqual("all_collected_tickers", runtime["V2_TREND_CONT"]["research_scope"])


class StrategyInventoryEndpointTests(unittest.TestCase):
    def test_real_auth_dependency_protects_read_only_inventory(self):
        from fastapi import Depends, FastAPI
        from api.middleware.auth import require_auth
        from api.routes.settings import router
        from auth.security import COOKIE_NAME
        import types
        users = types.ModuleType("auth.users")
        users.get_user = lambda user_id: None
        app = FastAPI()
        app.include_router(router, dependencies=[Depends(require_auth)])
        async def request(method="GET", cookie=False):
            messages = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            headers = [(b"cookie", f"{COOKIE_NAME}=test-only-cookie".encode())] if cookie else []
            await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                       "method": method, "scheme": "http", "path": "/api/settings/strategies/tested",
                       "raw_path": b"/api/settings/strategies/tested", "query_string": b"",
                       "headers": headers, "client": ("127.0.0.1", 1234), "server": ("test", 80),
                       "root_path": ""}, receive, send)
            return messages[0]["status"], json.loads(b"".join(m.get("body", b"") for m in messages))
        self.assertEqual(401, asyncio.run(request())[0])
        for user in ("alice", "bob"):
                with patch.dict("sys.modules", {"auth.users": users}), \
                     patch("api.middleware.auth.jwt.decode", return_value={"sub": user, "session_version": 1}), \
                     patch("api.middleware.auth.jwt_secret", return_value="test-only-secret"), \
                     patch.object(users, "get_user", return_value={"user_id": user, "username": user, "session_version": 1, "is_admin": False}), \
                     patch("config.save_settings") as save, patch("config.get_api_keys") as keys:
                    status, body = asyncio.run(request(cookie=True))
                    self.assertEqual(200, status)
                    self.assertIn("strategies", body)
                    save.assert_not_called()
                    keys.assert_not_called()
        self.assertEqual(405, asyncio.run(request("POST"))[0])


if __name__ == "__main__":
    unittest.main()
