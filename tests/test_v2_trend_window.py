from datetime import datetime
import unittest

from strategies.trend_continuation_v2 import is_validated_entry_time


class V2TrendWindowTests(unittest.TestCase):
    def test_includes_selected_window_and_excludes_boundaries(self) -> None:
        self.assertFalse(is_validated_entry_time(datetime(2026, 8, 10, 10, 14)))
        self.assertTrue(is_validated_entry_time(datetime(2026, 8, 10, 10, 15)))
        self.assertTrue(is_validated_entry_time(datetime(2026, 8, 10, 11, 29)))
        self.assertFalse(is_validated_entry_time(datetime(2026, 8, 10, 11, 30)))

    def test_converts_aware_utc_timestamp_to_eastern(self) -> None:
        self.assertTrue(is_validated_entry_time("2026-08-10T14:15:00+00:00"))
        self.assertFalse(is_validated_entry_time("2026-08-10T15:30:00+00:00"))


if __name__ == "__main__":
    unittest.main()
