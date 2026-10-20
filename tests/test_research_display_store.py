import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from api.research_display_store import load, save


class DisplayStoreTests(unittest.TestCase):
    def test_scope_isolation_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "api.research_display_store._path", return_value=Path(directory)/"display.sqlite3"):
            key = ("admin", "paper", "settings", 90, "2026-01-01", "2026-03-31")
            save(key, 10, {"strategies": [1]})
            self.assertEqual(load(key), (10, {"strategies": [1]}))
            self.assertIsNone(load(("other", *key[1:])))
            self.assertIsNone(load(("admin", "live", *key[2:])))
            for i in range(15):
                save((str(i),), i+20, {"strategies": []})
            self.assertIsNone(load(key))
