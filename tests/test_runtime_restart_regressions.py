from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from trading.controls.helpers import _refresh_session_pnl
from trading.state import get_user_state


class RuntimeRestartRegressionTests(unittest.TestCase):
    def test_loop_imports_watchlist_reader_used_during_restart_restore(self) -> None:
        source = Path("trading/loop/inner.py").read_text()
        tree = ast.parse(source)
        scanner_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "scanner"
            for alias in node.names
        }
        self.assertIn("get_watchlist", scanner_imports)

    def test_session_pnl_uses_supported_account_scoped_trade_query(self) -> None:
        state = get_user_state("runtime-regression-user")
        state.update({
            "mode": "paper",
            "broker_account_id": "alpaca:paper:account-1",
            "session_pnl": 0.0,
        })
        today = __import__("trading.controls.helpers", fromlist=["_now_et"])._now_et().date().isoformat()
        trades = [
            {"realized_pnl": 25.0, "exit_time": f"{today}T10:00:00"},
            {"realized_pnl": -5.0, "exit_time": f"{today}T11:00:00"},
        ]

        with patch("database.get_all_trades", return_value=trades) as query, patch(
            "config.atomic_update_json",
        ), patch(
            "config.get_bot_state_path", return_value=Path("/tmp/runtime-regression-bot-state.json"),
        ):
            pnl = _refresh_session_pnl("runtime-regression-user")

        self.assertEqual(20.0, pnl)
        query.assert_called_once_with(
            limit=200,
            mode="paper",
            broker_account_id="alpaca:paper:account-1",
            user_id="runtime-regression-user",
        )


if __name__ == "__main__":
    unittest.main()
