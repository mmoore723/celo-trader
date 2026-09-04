from datetime import datetime, timezone
import asyncio
from contextlib import closing, contextmanager
from pathlib import Path
import json
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from jose import jwt

from api.routes.option_chart import router
from auth.context import get_current_user_id
from auth.security import COOKIE_NAME, JWT_ALGORITHM
from database.option_chart import read_option_chart
from database.schema import _CREATE_TRADES, _CREATE_OPTION_QUOTE_OBSERVATIONS

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)
SECRET = "offline-chart-test-secret-not-for-production-123456789"


@contextmanager
def connect(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        yield conn


class OptionChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for user in ("alice", "bob"):
            folder = self.root / user
            folder.mkdir()
            for mode in ("paper", "live"):
                with connect(folder / f"trades_{mode}.db") as conn:
                    conn.executescript(_CREATE_TRADES + _CREATE_OPTION_QUOTE_OBSERVATIONS)
                    conn.execute("ALTER TABLE trades ADD COLUMN stop_price REAL")
                    conn.execute("ALTER TABLE trades ADD COLUMN target_price REAL")
                    conn.execute("""INSERT INTO trades (id,ticker,contract_symbol,option_type,strike,expiry,
                        contracts,entry_price,entry_time,paper,broker_account_id,stop_price,target_price)
                        VALUES (1,?,'TEST_OPTION','put',100,'2026-09-04',2,4,'2026-09-04T10:00:00',?,?,3,6)""",
                        (user.upper(), int(mode == "paper"), user + "-account"))
        self.db = self.root / "alice/trades_paper.db"

    def tearDown(self):
        self.temp.cleanup()

    def quote(self, stamp="2026-09-04T10:05:00", bid=4.1, ask=4.2, source="tradier_quote", symbol="TEST_OPTION"):
        with connect(self.db) as conn:
            conn.execute("""INSERT INTO option_quote_observations
                (trade_id,observed_at,observed_minute,observation_kind,contract_symbol,bid,ask,source)
                VALUES (1,?,?,'mark',?,?,?,?)""", (stamp, stamp[:16], symbol, bid, ask, source))

    def read(self, **kwargs):
        return read_option_chart(self.db, trade_id=1, account_id="alice-account", paper=True, now=NOW, **kwargs)

    def test_real_quotes_and_et_timestamp_only_no_synthetic_candles(self):
        self.quote()
        result = self.read()
        self.assertEqual(result["entry_time"], datetime(2026, 9, 4, 14, tzinfo=timezone.utc).timestamp())
        self.assertEqual(result["quotes"], [{"time": 1788530700.0, "bid": 4.1, "ask": 4.2}])
        self.assertEqual(result["option_type"], "put")
        self.assertNotIn("ohlc", result)
        json.dumps(result, allow_nan=False)

    def test_mode_account_missing_file_fail_closed(self):
        for account, paper in (("bob-account", True), ("", True), ("alice-account", False)):
            self.assertIsNone(read_option_chart(self.db, trade_id=1, account_id=account, paper=paper))
        missing = self.root / "missing.db"
        self.assertIsNone(read_option_chart(missing, trade_id=1, account_id="alice-account", paper=True))
        self.assertFalse(missing.exists())

    def test_reader_does_not_change_database(self):
        before = self.db.read_bytes()
        self.read()
        self.assertEqual(self.db.read_bytes(), before)

    def test_router_is_registered_in_production_app(self):
        import ast
        app = ast.parse((Path(__file__).parents[1] / "api/main/app.py").read_text())
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router" and node.args
            and ast.unparse(node.args[0]) == "option_chart.router" for node in ast.walk(app)))

    def test_invalid_foreign_and_out_of_lifetime_quotes_removed(self):
        for stamp in ("bad", "2026-09-04T09:59:59", "2026-09-04T11:01:00"):
            self.quote(stamp=stamp)
        for bid, ask in ((float("inf"), 5), (4, float("inf")), (-1, 4), (5, 4), (0, 0)):
            self.quote(bid=bid, ask=ask)
        self.quote(symbol="ANOTHER_OPTION")
        self.quote(source="alpaca_indicative")
        self.quote(bid=0, ask=0.05)
        self.assertEqual(len(self.read()["quotes"]), 1)
        self.assertEqual(self.read()["quotes"][0]["bid"], 0)

    def test_closed_trade_fill_not_fabricated_from_last_quote(self):
        self.quote()
        self.quote(stamp="2026-09-04T10:30:01")
        with connect(self.db) as conn:
            conn.execute("UPDATE trades SET exit_time='2026-09-04T10:30:00',exit_price=4.3,realized_pnl=60,status='closed'")
        data = self.read()
        self.assertEqual(len(data["quotes"]), 1)
        self.assertEqual(data["exit_price"], 4.3)
        self.assertEqual(data["realized_pnl"], 60)

    def test_missing_history_and_reference_levels_are_not_invented(self):
        with connect(self.db) as conn:
            conn.execute("DROP TABLE option_quote_observations")
            conn.execute("UPDATE trades SET stop_price=NULL,target_price=NULL")
        data = self.read()
        self.assertEqual(data["quotes"], [])
        self.assertIsNone(data["stop_price"])
        self.assertIsNone(data["target_price"])

    def test_authentication_cross_user_mode_and_bad_requests(self):
        app = FastAPI()
        app.include_router(router)
        cookie = ""
        def get(url):
            from types import SimpleNamespace
            from urllib.parse import urlsplit
            target, messages = urlsplit(url), []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            async def request():
                await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": "GET", "scheme": "http", "path": target.path,
                    "query_string": target.query.encode(), "root_path": "",
                    "headers": [(b"cookie", cookie.encode())], "client": ("testclient", 1),
                    "server": ("offline", 80)}, receive, send)
            asyncio.run(request())
            body = b"".join(m.get("body", b"") for m in messages).decode()
            return SimpleNamespace(status_code=messages[0]["status"], text=body, json=lambda: json.loads(body))
        def get_user(uid):
            return {"user_id": uid, "username": uid, "session_version": 1, "is_admin": False}
        with patch("api.middleware.auth.jwt_secret", return_value=SECRET), \
             patch.dict("sys.modules", {"auth.users": types.SimpleNamespace(get_user=get_user)}), \
             patch("config.paths.get_user_data_dir", side_effect=lambda **kw: self.root / get_current_user_id()), \
             patch("config.get_settings", side_effect=lambda: {"active_broker_account_id": get_current_user_id()+"-account"}):
            self.assertEqual(get("/api/trades/1/option-chart").status_code, 401)
            for user in ("alice", "bob", "alice"):
                token = jwt.encode({"sub": user, "session_version": 1}, SECRET, algorithm=JWT_ALGORITHM)
                cookie = f"{COOKIE_NAME}={token}"
                for mode in ("paper", "live"):
                    response = get(f"/api/trades/1/option-chart?mode={mode}")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["ticker"], user.upper())
                    self.assertEqual(response.json()["mode"], mode)
            self.assertEqual(get("/api/trades/1/option-chart?mode=wrong").status_code, 422)
            self.assertEqual(get("/api/trades/0/option-chart").status_code, 422)
            self.assertEqual(get("/api/trades/999/option-chart").status_code, 404)
            token = jwt.encode({"sub": "alice", "session_version": 0}, SECRET, algorithm=JWT_ALGORITHM)
            cookie = f"{COOKIE_NAME}={token}"
            self.assertEqual(get("/api/trades/1/option-chart").status_code, 401)


if __name__ == "__main__":
    unittest.main()
