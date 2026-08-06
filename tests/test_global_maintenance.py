"""Regression coverage for the system-wide maintenance trading halt."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import settings_store


class GlobalMaintenanceTests(unittest.TestCase):
    def test_state_is_shared_and_message_is_cleared_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "system_maintenance.json"
            with patch.object(settings_store, "SYSTEM_MAINTENANCE_PATH", path):
                self.assertEqual(
                    {"maintenance_mode": False, "maintenance_message": ""},
                    settings_store.get_maintenance_state(),
                )
                settings_store.save_maintenance_state(True, "  Trading halted for maintenance.  ")
                self.assertEqual(
                    {
                        "maintenance_mode": True,
                        "maintenance_message": "Trading halted for maintenance.",
                    },
                    settings_store.get_maintenance_state(),
                )
                self.assertEqual(True, json.loads(path.read_text())["maintenance_mode"])
                settings_store.save_maintenance_state(False, "must not persist")
                self.assertEqual(
                    {"maintenance_mode": False, "maintenance_message": ""},
                    settings_store.get_maintenance_state(),
                )

    def test_malformed_state_fails_closed_to_no_halt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "system_maintenance.json"
            path.write_text("not json")
            with patch.object(settings_store, "SYSTEM_MAINTENANCE_PATH", path):
                self.assertEqual(
                    {"maintenance_mode": False, "maintenance_message": ""},
                    settings_store.get_maintenance_state(),
                )


if __name__ == "__main__":
    unittest.main()
