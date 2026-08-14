from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from config.strategy_catalog import (
    REVIEWED_STRATEGIES, ensure_reviewed_ticker_coverage, is_allowed_ticker,
)


class ReviewedStrategyCatalogTests(unittest.TestCase):
    def test_production_router_contains_only_reviewed_bar_evaluators(self) -> None:
        from strategy_router.evaluators import ACTIVE_STRATEGIES

        self.assertEqual(
            ["V2_ORB_PULLBACK", "V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG"],
            [strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES],
        )
        self.assertTrue(
            set(strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES)
            <= set(REVIEWED_STRATEGIES)
        )

    def test_scope_is_explicit_per_strategy_and_ticker(self) -> None:
        self.assertTrue(is_allowed_ticker("V2_ORB_PULLBACK", "TSLA"))
        self.assertFalse(is_allowed_ticker("V2_ORB_PULLBACK", "SPY"))
        self.assertTrue(is_allowed_ticker("V2_SPY_TREND_CONT", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_TREND_CONT", "QQQ"))
        self.assertTrue(is_allowed_ticker("V2_SPY_AFTERNOON_FVG", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_AFTERNOON_FVG", "TSLA"))

    def test_scanner_list_is_preserved_and_covered_for_enabled_rules(self) -> None:
        self.assertEqual(
            ["QQQ", "NVDA", "TSLA", "SPY"],
            ensure_reviewed_ticker_coverage(
                ["QQQ", "NVDA"], {"V2_SPY_TREND_CONT", "V2_ORB_PULLBACK"},
            ),
        )

    def test_spy_trend_exit_matches_its_one_position_paid_data_selection(self) -> None:
        self.assertEqual(30, REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"].exit_minutes)

    def test_spy_afternoon_fvg_uses_reviewed_30_minute_exit(self) -> None:
        self.assertEqual(30, REVIEWED_STRATEGIES["V2_SPY_AFTERNOON_FVG"].exit_minutes)

    def test_stale_user_validation_list_cannot_restore_unreviewed_rule(self) -> None:
        """A prior browser save must not turn an unfinished study into a pilot."""
        from config import settings_store

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_dir = root / "evidence-test"
            user_dir.mkdir()
            (user_dir / "settings.json").write_text(json.dumps({
                "validated_strategy_ids": [
                    "V2_SPY_AFTERNOON_FVG",
                    "V2_SPY_AFTERNOON_REVERSAL",
                ],
                "strategy_spy_afternoon_fvg_v2_enabled": True,
                "strategy_spy_afternoon_reversal_v2_enabled": True,
                "strategy_tsla_noise_momentum_v2_enabled": True,
                "strategy_mid_enabled": True,
                "strategy_liqsweep_enabled": True,
            }))
            with patch.object(settings_store, "get_user_data_dir", return_value=user_dir), \
                 patch.object(settings_store, "SETTINGS_PATH", root / "missing-legacy.json"):
                settings = settings_store.get_settings(user_id="evidence-test")

        self.assertEqual(sorted(REVIEWED_STRATEGIES), settings["validated_strategy_ids"])
        self.assertIn("V2_SPY_AFTERNOON_FVG", settings["validated_strategy_ids"])
        self.assertNotIn("V2_SPY_AFTERNOON_REVERSAL", settings["validated_strategy_ids"])
        self.assertFalse(settings["strategy_spy_afternoon_reversal_v2_enabled"])
        self.assertFalse(settings["strategy_tsla_noise_momentum_v2_enabled"])
        self.assertFalse(settings["strategy_mid_enabled"])
        self.assertFalse(settings["strategy_liqsweep_enabled"])


if __name__ == "__main__":
    unittest.main()
