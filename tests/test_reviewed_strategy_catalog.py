from __future__ import annotations

import unittest
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from config.strategy_catalog import (
    REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids,
    enabled_observation_strategy_ids,
    ensure_reviewed_ticker_coverage, is_allowed_ticker, public_strategy_catalog,
    reviewed_execution_strategy_ids, reviewed_strategy_ids,
    reviewed_research_exit_minutes, reviewed_strategy_integrity_errors,
    strategy_ids_for_source,
)


class ReviewedStrategyCatalogTests(unittest.TestCase):
    def test_production_router_contains_only_reviewed_bar_evaluators(self) -> None:
        from strategy_router.evaluators import ACTIVE_STRATEGIES

        self.assertEqual(
            strategy_ids_for_source("bar_close"),
            {strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES},
        )
        self.assertEqual({"V2_ORB_PULLBACK", "APPROVED_V2_ORB_PULLBACK"}, strategy_ids_for_source("live_retouch"))
        self.assertEqual(
            {"V2_TSLA_TWO_LEG_TREND_PULLBACK"},
            strategy_ids_for_source("one_minute_state"),
        )
        self.assertTrue(
            set(strategy_id for strategy_id, _evaluate in ACTIVE_STRATEGIES)
            <= set(REVIEWED_STRATEGIES)
        )

    def test_enabled_registry_respects_paper_only_evidence_status(self) -> None:
        settings = {rule.setting_key: True for rule in REVIEWED_STRATEGIES.values()}
        self.assertEqual(
            {"V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG", "V2_FAILED_OR_BREAK_VWAP_REVERSION"},
            enabled_reviewed_strategy_ids(settings, ticker="SPY", paper=True),
        )
        self.assertEqual(
            {"V2_SPY_AFTERNOON_FVG", "V2_FAILED_OR_BREAK_VWAP_REVERSION"},
            enabled_reviewed_strategy_ids(settings, ticker="SPY", paper=False),
        )

    def test_exact_qualified_live_pair_survives_central_enabled_filter(self) -> None:
        rule = REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"]
        settings = {rule.setting_key: True, "paper_trading": False}
        with patch.dict(REVIEWED_STRATEGIES, {rule.strategy_id: replace(rule, paper_only=True)}), \
             patch("config.strategy_ticker_recommendations.is_live_enabled_pair", return_value=True), \
             patch("config.strategy_ticker_recommendations.is_user_authorized_ticker", return_value=True), \
             patch("config.strategy_ticker_recommendations.has_user_live_enabled", return_value=True):
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

    def test_spy_trend_evidence_describes_the_exact_deployed_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rule = REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"]
        evidence = json.loads((root / rule.evidence_artifact).read_text())
        self.assertEqual("2.1.0", rule.version)
        self.assertEqual(rule.version, evidence["strategy_version"])
        replay = evidence["source_report_reconciliation"]
        self.assertFalse(replay["all_reported_markouts_reachable_by_production"])
        self.assertEqual(70, replay["reported_markouts_not_emittable_by_production"])
        self.assertEqual(72, replay["exact_deployed_policy_markouts"])
        self.assertEqual(46, replay["repaired_three_bar_policy_markouts"])
        self.assertEqual(46, evidence["display_metrics"]["trades"])
        self.assertAlmostEqual(1.75, evidence["display_metrics"]["profit_factor"])
        self.assertTrue(evidence["display_metrics"]["meets_target"])
        self.assertEqual(28, evidence["all"]["raw_quote_wins_before_costs"])
        self.assertEqual(25, evidence["all"]["wins"])
        self.assertAlmostEqual(54.35, evidence["all"]["win_rate_pct"])
        self.assertEqual("promising_underpowered", rule.evidence_grade)
        self.assertTrue(rule.paper_only)

    def test_spy_afternoon_fvg_uses_reviewed_30_minute_exit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rule = REVIEWED_STRATEGIES["V2_SPY_AFTERNOON_FVG"]
        evidence = json.loads((root / rule.evidence_artifact).read_text())
        self.assertEqual(30, rule.exit_minutes)
        self.assertEqual("2.1.0", rule.version)
        self.assertEqual(19, evidence["historical_repair_diagnostic"]["repaired_all"]["trades"])
        self.assertAlmostEqual(
            2.2165,
            evidence["historical_repair_diagnostic"]["repaired_all"]["profit_factor"],
        )
        self.assertEqual(
            "bullish retest close above EMA8; bearish retest close below EMA8",
            evidence["selected_policy"]["trigger_confirmation"],
        )

    def test_spy_failed_range_recovery_uses_reviewed_30_minute_exit(self) -> None:
        self.assertEqual(30, REVIEWED_STRATEGIES["V2_FAILED_OR_BREAK_VWAP_REVERSION"].exit_minutes)

    def test_spy_failed_range_evidence_is_not_presented_as_a_pass(self) -> None:
        rule = REVIEWED_STRATEGIES["V2_FAILED_OR_BREAK_VWAP_REVERSION"]
        root = Path(__file__).resolve().parents[1]
        evidence = json.loads((root / rule.evidence_artifact).read_text())
        self.assertEqual("2.1.0", rule.version)
        self.assertEqual(rule.version, evidence["strategy_version"])
        self.assertEqual("promising_inconsistent", rule.evidence_grade)

    def test_tsla_two_leg_new_entry_cohort_does_not_claim_old_returns(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rule = REVIEWED_STRATEGIES["V2_TSLA_TWO_LEG_TREND_PULLBACK"]
        evidence = json.loads((root / rule.evidence_artifact).read_text())
        self.assertEqual("2.2.0", rule.version)
        self.assertEqual(90, rule.exit_minutes)
        self.assertEqual("fresh_directionally_confirmed_reclaim_episodes", evidence["selected_policy"]["variant"])
        self.assertIsNone(evidence["selected_policy"]["session_entry_limit"])
        self.assertIsNone(evidence["display_metrics"]["profit_factor"])
        self.assertEqual(0, evidence["display_metrics"]["trades"])
        predecessor = json.loads((root / evidence["predecessor"]["artifact"]).read_text())
        self.assertEqual(76, predecessor["historical_repair_diagnostic"]["repaired_all"]["trades"])
        self.assertEqual("promising_inconsistent", rule.evidence_grade)

    def test_displacement_is_paper_tradable_only_on_its_reviewed_tickers(self) -> None:
        strategy_id = "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"
        rule = REVIEWED_STRATEGIES[strategy_id]
        settings = {rule.setting_key: True}
        self.assertEqual("0.2.0", rule.version)
        self.assertIsNone(rule.exit_minutes)
        self.assertEqual(90, rule.research_exit_minutes)
        self.assertEqual(5, rule.minimum_session_minutes)
        self.assertFalse(rule.observation_only)
        self.assertTrue(rule.paper_only)
        self.assertIn(strategy_id, enabled_reviewed_strategy_ids(settings, ticker="TSLA", paper=True))
        self.assertIn(strategy_id, enabled_reviewed_strategy_ids(settings, ticker="AMZN", paper=True))
        self.assertNotIn(strategy_id, enabled_reviewed_strategy_ids(settings, ticker="SPY", paper=True))
        self.assertNotIn(strategy_id, enabled_reviewed_strategy_ids(settings, ticker="TSLA", paper=False))
        row = next(
            item for item in public_strategy_catalog(settings)
            if item["strategy_id"] == strategy_id
        )
        self.assertEqual(7.21, row["backtest"]["profit_factor"])
        self.assertEqual(6, row["backtest"]["trades"])
        self.assertTrue(row["backtest"]["meets_numeric_target"])
        self.assertFalse(row["backtest"]["sample_is_sufficient"])

    def test_research_only_rules_have_a_fixed_forward_mark(self) -> None:
        self.assertEqual(90, reviewed_research_exit_minutes("CTX_ORB_NR7_OR_INSIDE"))
        self.assertEqual(30, reviewed_research_exit_minutes("V2_SPY_AFTERNOON_FVG"))

    def test_observation_scope_is_all_collected_tickers_not_trading_scope(self) -> None:
        rule = REVIEWED_STRATEGIES["CTX_ORB_NR7_OR_INSIDE"]
        settings = {rule.setting_key: True}
        self.assertIn(rule.strategy_id, enabled_observation_strategy_ids(settings, ticker="AAPL"))
        self.assertFalse(is_allowed_ticker(rule.strategy_id, "AAPL"))

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
            if strategy.evidence_grade == "passed_declared_holdout":
                self.assertTrue(evidence["display_metrics"]["meets_target"])

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

    def test_public_catalog_keeps_failed_trend_out_of_live_execution(self) -> None:
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

    def test_live_catalog_respects_each_execution_strategy_evidence_status(self) -> None:
        settings = {
            "paper_trading": False,
            **{rule.setting_key: True for rule in REVIEWED_STRATEGIES.values()},
        }
        rows = public_strategy_catalog(settings)
        self.assertEqual(set(REVIEWED_STRATEGIES), {row["strategy_id"] for row in rows})
        for row in rows:
            if row["observation_only"]:
                self.assertFalse(row["live_eligible"], row["strategy_id"])
                self.assertFalse(row["eligible_in_current_mode"], row["strategy_id"])
                self.assertFalse(row["execution_enabled"], row["strategy_id"])
                self.assertTrue(row["observation_enabled"], row["strategy_id"])
            else:
                expected_live = not REVIEWED_STRATEGIES[row["strategy_id"]].paper_only
                self.assertEqual(expected_live, row["live_eligible"], row["strategy_id"])
                self.assertEqual(expected_live, row["eligible_in_current_mode"], row["strategy_id"])
                self.assertEqual(expected_live, row["execution_enabled"], row["strategy_id"])

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

        self.assertEqual(sorted(reviewed_execution_strategy_ids()), settings["validated_strategy_ids"])
        self.assertIn("V2_SPY_AFTERNOON_FVG", settings["validated_strategy_ids"])
        self.assertNotIn("V2_SPY_AFTERNOON_REVERSAL", settings["validated_strategy_ids"])
        self.assertNotIn("strategy_spy_afternoon_reversal_v2_enabled", settings)
        self.assertNotIn("strategy_tsla_noise_momentum_v2_enabled", settings)
        self.assertNotIn("strategy_mid_enabled", settings)
        self.assertNotIn("strategy_liqsweep_enabled", settings)

    def test_observation_switch_cannot_grant_order_authority(self) -> None:
        strategy_id = "CTX_ORB_NR7_OR_INSIDE"
        rule = REVIEWED_STRATEGIES[strategy_id]
        settings = {rule.setting_key: True, "paper_trading": True}
        self.assertEqual({strategy_id}, enabled_observation_strategy_ids(settings, ticker="TSLA"))
        self.assertEqual(set(), enabled_reviewed_strategy_ids(settings, ticker="TSLA", paper=True))
        self.assertNotIn(strategy_id, reviewed_execution_strategy_ids())

    def test_catalog_exposes_contextual_pf_not_a_naked_number(self) -> None:
        settings = {rule.setting_key: True for rule in REVIEWED_STRATEGIES.values()}
        row = next(item for item in public_strategy_catalog(settings) if item["strategy_id"] == "CTX_ORB_NR7_OR_INSIDE")
        self.assertEqual(1.70, row["backtest"]["profit_factor"])
        self.assertEqual(32, row["backtest"]["trades"])
        self.assertIn("TSLA", row["backtest"]["scope"])
        self.assertIn("before January 30, 2026 PF 1.09", row["backtest"]["comparison"])
        self.assertNotIn("before May 1, 2026 PF 1.09", row["backtest"]["comparison"])

    def test_observer_switch_is_isolated_per_user(self) -> None:
        from config import settings_store

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for user_id in ("user-a", "user-b"):
                (root / user_id).mkdir()

            def user_dir(user_id: str, create: bool = True) -> Path:
                path = root / user_id
                if create:
                    path.mkdir(exist_ok=True)
                return path

            with patch.object(settings_store, "get_user_data_dir", side_effect=user_dir), \
                 patch.object(settings_store, "SETTINGS_PATH", root / "missing-legacy.json"):
                settings_store.save_settings(
                    {"observe_ctx_orb_nr7_inside_enabled": False}, user_id="user-a",
                )
                user_a = settings_store.get_settings(user_id="user-a")
                user_b = settings_store.get_settings(user_id="user-b")

        self.assertFalse(user_a["observe_ctx_orb_nr7_inside_enabled"])
        self.assertTrue(user_b["observe_ctx_orb_nr7_inside_enabled"])
        self.assertNotIn("CTX_ORB_NR7_OR_INSIDE", user_a["validated_strategy_ids"])


if __name__ == "__main__":
    unittest.main()
