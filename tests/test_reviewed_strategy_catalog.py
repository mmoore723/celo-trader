from __future__ import annotations

import unittest
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from config.strategy_catalog import (
    REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids,
    ensure_reviewed_ticker_coverage, is_allowed_ticker, public_strategy_catalog,
    reviewed_strategy_ids, reviewed_strategy_integrity_errors, strategy_ids_for_source,
)


class ReviewedStrategyCatalogTests(unittest.TestCase):
    def test_production_router_contains_only_reviewed_bar_evaluators(self) -> None:
        from strategy_router.evaluators import ACTIVE_STRATEGIES

        self.assertEqual(
            ["V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG", "V2_FAILED_OR_BREAK_VWAP_REVERSION"],
            [strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES],
        )
        self.assertEqual({"V2_ORB_PULLBACK"}, strategy_ids_for_source("live_retouch"))
        self.assertEqual(
            {"V2_TSLA_TWO_LEG_TREND_PULLBACK"},
            strategy_ids_for_source("one_minute_state"),
        )
        self.assertTrue(
            set(strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES)
            <= set(REVIEWED_STRATEGIES)
        )

    def test_enabled_registry_enforces_ticker_and_paper_scope(self) -> None:
        settings = {rule.setting_key: True for rule in REVIEWED_STRATEGIES.values()}
        self.assertEqual(
            {"V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG", "V2_FAILED_OR_BREAK_VWAP_REVERSION"},
            enabled_reviewed_strategy_ids(settings, ticker="SPY", paper=True),
        )
        self.assertEqual(set(), enabled_reviewed_strategy_ids(settings, ticker="SPY", paper=False))

    def test_exact_qualified_live_pair_survives_central_enabled_filter(self) -> None:
        rule = REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"]
        settings = {rule.setting_key: True, "paper_trading": False}
        with patch.dict(REVIEWED_STRATEGIES, {rule.strategy_id: replace(rule, paper_only=True)}), \
             patch("config.strategy_ticker_recommendations.is_live_pilot_pair", return_value=True), \
             patch("config.strategy_ticker_recommendations.is_user_authorized_ticker", return_value=True), \
             patch("config.strategy_ticker_recommendations.has_user_live_pilot", return_value=True):
            self.assertEqual(
                {rule.strategy_id}, enabled_reviewed_strategy_ids(settings, paper=False),
            )
            self.assertEqual(
                {rule.strategy_id},
                enabled_reviewed_strategy_ids(settings, ticker="QQQ", paper=False),
            )

    def test_scope_is_explicit_per_strategy_and_ticker(self) -> None:
        self.assertTrue(is_allowed_ticker("V2_ORB_PULLBACK", "TSLA"))
        self.assertFalse(is_allowed_ticker("V2_ORB_PULLBACK", "SPY"))
        self.assertTrue(is_allowed_ticker("V2_SPY_TREND_CONT", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_TREND_CONT", "QQQ"))
        self.assertTrue(is_allowed_ticker("V2_SPY_AFTERNOON_FVG", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_SPY_AFTERNOON_FVG", "TSLA"))
        self.assertTrue(is_allowed_ticker("V2_FAILED_OR_BREAK_VWAP_REVERSION", "SPY"))
        self.assertFalse(is_allowed_ticker("V2_FAILED_OR_BREAK_VWAP_REVERSION", "TSLA"))

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

    def test_spy_failed_range_recovery_uses_reviewed_30_minute_exit(self) -> None:
        self.assertEqual(30, REVIEWED_STRATEGIES["V2_FAILED_OR_BREAK_VWAP_REVERSION"].exit_minutes)

    def test_registry_is_versioned_and_references_real_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for strategy in REVIEWED_STRATEGIES.values():
            self.assertTrue(strategy.version)
            self.assertEqual("paper_candidate", strategy.status)
            self.assertTrue(strategy.implementation)
            evidence_path = root / strategy.evidence_artifact
            self.assertTrue(evidence_path.is_file(), strategy.strategy_id)
            evidence = json.loads(evidence_path.read_text())
            self.assertEqual(strategy.strategy_id, evidence["strategy_id"])
            self.assertEqual(strategy.version, evidence["strategy_version"])
            self.assertEqual(strategy.status, evidence["status"])
            self.assertEqual(strategy.evidence_grade, evidence["evidence_grade"])
            self.assertEqual(sorted(strategy.tickers), evidence["ticker_scope"])
            self.assertEqual(strategy.implementation, evidence["implementation"])
            self.assertTrue(evidence["implementation_sha256_at_review"])
            self.assertTrue(evidence["source_reports"])
            self.assertTrue(evidence["decision"])

    def test_reviewed_implementation_hashes_match_evidence(self) -> None:
        self.assertEqual({}, reviewed_strategy_integrity_errors())

    def test_integrity_failure_removes_only_drifted_strategy(self) -> None:
        with patch(
            "config.strategy_catalog.reviewed_strategy_integrity_errors",
            return_value={"V2_ORB_PULLBACK": ("implementation_hash_mismatch",)},
        ):
            self.assertNotIn("V2_ORB_PULLBACK", reviewed_strategy_ids())
            self.assertIn("V2_SPY_TREND_CONT", reviewed_strategy_ids())
            settings = {rule.setting_key: True for rule in REVIEWED_STRATEGIES.values()}
            orb = next(
                item for item in public_strategy_catalog(settings)
                if item["strategy_id"] == "V2_ORB_PULLBACK"
            )
            self.assertFalse(orb["enabled"])
            self.assertEqual(["implementation_hash_mismatch"], orb["integrity_errors"])

    def test_public_catalog_resolves_account_switches_server_side(self) -> None:
        settings = {rule.setting_key: False for rule in REVIEWED_STRATEGIES.values()}
        settings[REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"].setting_key] = True
        catalog = public_strategy_catalog(settings)
        enabled = {item["strategy_id"] for item in catalog if item["enabled"]}
        self.assertEqual({"V2_SPY_TREND_CONT"}, enabled)

    def test_public_catalog_separates_switch_from_current_mode_execution(self) -> None:
        rule = REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"]
        settings = {rule.setting_key: True, "paper_trading": False}
        row = next(
            item for item in public_strategy_catalog(settings)
            if item["strategy_id"] == rule.strategy_id
        )
        self.assertTrue(row["enabled"])
        self.assertEqual("live", row["account_mode"])
        self.assertFalse(row["live_eligible"])
        self.assertFalse(row["eligible_in_current_mode"])
        self.assertFalse(row["execution_enabled"])
        self.assertEqual("shadow_observation", row["validation_state"])
        self.assertFalse(row["observation_requires_paper_mode"])
        self.assertEqual("shadow_observation", row["live_promotion"]["stage"])
        self.assertTrue(row["live_promotion"]["blockers"])

    def test_paper_mode_switch_is_reported_as_executable(self) -> None:
        rule = REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"]
        settings = {rule.setting_key: True, "paper_trading": True}
        row = next(
            item for item in public_strategy_catalog(settings)
            if item["strategy_id"] == rule.strategy_id
        )
        self.assertTrue(row["eligible_in_current_mode"])
        self.assertTrue(row["execution_enabled"])

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
        self.assertNotIn("strategy_spy_afternoon_reversal_v2_enabled", settings)
        self.assertNotIn("strategy_tsla_noise_momentum_v2_enabled", settings)
        self.assertNotIn("strategy_mid_enabled", settings)
        self.assertNotIn("strategy_liqsweep_enabled", settings)


if __name__ == "__main__":
    unittest.main()
