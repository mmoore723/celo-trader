from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database.schema import _init_db_at
from database.settings_audit import (
    get_strategy_setting_changes,
    record_strategy_setting_changes,
)


class StrategySettingAuditTests(unittest.TestCase):
    def test_strategy_switch_changes_are_append_only_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "trades_paper.db"
            _init_db_at(db_path)
            with patch("database.connection.get_db_path", return_value=db_path):
                record_strategy_setting_changes("user-1", [
                    ("V2_SPY_TREND_CONT", "strategy_spy_trend_cont_v2_enabled", True, False),
                    ("V2_ORB_PULLBACK", "strategy_orb_pullback_v2_enabled", False, True),
                ])
                changes = get_strategy_setting_changes()

        self.assertEqual(2, len(changes))
        self.assertEqual("V2_ORB_PULLBACK", changes[0]["strategy_id"])
        self.assertFalse(changes[0]["previous_enabled"])
        self.assertTrue(changes[0]["new_enabled"])
        self.assertEqual("user-1", changes[0]["actor_user_id"])


if __name__ == "__main__":
    unittest.main()
