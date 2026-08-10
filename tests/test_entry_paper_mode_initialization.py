"""Regression guard for the paper-mode initialization order in the entry tick."""

from pathlib import Path
import unittest


class EntryPaperModeInitializationTests(unittest.TestCase):
    def test_paper_mode_exists_before_observation_lane_uses_it(self):
        source = (Path(__file__).resolve().parents[1] / "trading" / "entry" / "tick.py").read_text()
        initialized_at = source.index('paper = bool(settings.get("paper_trading", True))')
        observed_at = source.index('if paper and bool(settings.get("shadow_ledger_enabled", True)):')
        self.assertLess(initialized_at, observed_at)


if __name__ == "__main__":
    unittest.main()
