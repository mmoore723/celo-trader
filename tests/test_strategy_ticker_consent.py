from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from config.strategy_ticker_recommendations import (
    approved_dynamic_tickers, consent_for, has_user_live_enabled,
    has_user_paper_enabled, is_live_enabled_pair, is_paper_enabled_pair,
    is_user_authorized_ticker, pair_key, public_recommendations,
    publish_qualified_recommendation, publish_recommendation, save_user_consent,
)


class StrategyTickerConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "recommendations.json"
        self.path_patch = patch("config.strategy_ticker_recommendations.RECOMMENDATIONS_PATH", self.path)
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.tempdir.cleanup()

    def _publish(self, *, qualified: bool = True) -> None:
        publish_recommendation(
            "V2_SPY_TREND_CONT", "QQQ",
            evidence_summary="Chronological quote validation passed.",
            qualification_verified=qualified,
        )

    def test_failed_static_strategy_remains_available_only_in_paper(self) -> None:
        self.assertTrue(is_user_authorized_ticker("V2_SPY_TREND_CONT", "SPY", {"paper_trading": True}))
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "SPY", {"paper_trading": False}))

    def test_new_pair_defaults_to_observation_and_fails_closed(self) -> None:
        self._publish()
        settings = {"paper_trading": True}
        self.assertEqual("observing", consent_for(settings, "V2_SPY_TREND_CONT", "QQQ"))
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", settings))
        self.assertEqual("pending", public_recommendations(settings)[0]["decision"])

    def test_exact_user_consent_enables_only_paper_pair(self) -> None:
        self._publish()
        user_a = {"paper_trading": True}
        user_a["strategy_ticker_consents"] = save_user_consent(user_a, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled")
        user_b = {"paper_trading": True}
        self.assertTrue(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_a))
        self.assertTrue(is_paper_enabled_pair("V2_SPY_TREND_CONT", "QQQ", user_a))
        self.assertTrue(has_user_paper_enabled("V2_SPY_TREND_CONT", user_a))
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_b))
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "TSLA", user_a))

    def test_consent_never_authorizes_live_mode(self) -> None:
        self._publish()
        settings = {"paper_trading": False, "strategy_ticker_consents": {pair_key("V2_SPY_TREND_CONT", "QQQ"): "paper_enabled"}}
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", settings))

    def test_paper_candidate_rejects_live_consent(self) -> None:
        self._publish()
        with self.assertRaises(ValueError):
            save_user_consent(
                {"paper_trading": False}, "V2_SPY_TREND_CONT", "QQQ", "live_enabled",
            )

    def test_public_recommendation_explains_mode_and_live_eligibility(self) -> None:
        self._publish()
        row = public_recommendations({"paper_trading": False})[0]
        self.assertEqual("live", row["account_mode"])
        self.assertFalse(row["live_eligible"])
        self.assertFalse(row["live_enabled"])
        self.assertEqual("shadow_observation", row["validation_state"])
        self.assertEqual("approval_needed", row["rollout_stage"])
        self.assertFalse(row["observation_requires_paper_mode"])

    def test_legacy_live_pilot_consent_is_read_as_normal_live_enablement(self) -> None:
        self._publish(qualified=False)
        settings = {
            "paper_trading": False,
            "strategy_ticker_consents": {
                pair_key("V2_SPY_TREND_CONT", "QQQ"): "live_pilot",
            },
        }
        self.assertEqual("live_enabled", consent_for(settings, "V2_SPY_TREND_CONT", "QQQ"))

    def test_exact_pair_promotion_does_not_require_global_catalog_promotion(self) -> None:
        from config.strategy_catalog import REVIEWED_STRATEGIES
        paper_candidate_rule = replace(REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"], paper_only=True)
        self._publish(qualified=False)
        # A manually published recommendation is intentionally insufficient.
        with patch.dict(REVIEWED_STRATEGIES, {"V2_SPY_TREND_CONT": paper_candidate_rule}), \
             patch("config.strategy_live_promotion.review_live_promotion") as review:
            review.return_value.ready = True
            with self.assertRaises(ValueError):
                save_user_consent({"paper_trading": False}, "V2_SPY_TREND_CONT", "QQQ", "live_enabled")

            from config.strategy_ticker_recommendations import load_recommendations
            rows = load_recommendations()
            rows[0]["qualification_verified"] = True
            from config.atomic_files import atomic_write_json
            atomic_write_json(self.path, {"recommendations": rows})
            user_a = {"paper_trading": False}
            user_a["strategy_ticker_consents"] = save_user_consent(
                user_a, "V2_SPY_TREND_CONT", "QQQ", "live_enabled",
            )
            user_b = {"paper_trading": False}
            self.assertTrue(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_a))
            self.assertTrue(is_live_enabled_pair("V2_SPY_TREND_CONT", "QQQ", user_a))
            self.assertEqual("live_enabled", public_recommendations(user_a)[0]["rollout_stage"])
            self.assertTrue(has_user_live_enabled("V2_SPY_TREND_CONT", user_a))
            self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_b))
            self.assertFalse(is_live_enabled_pair("V2_SPY_TREND_CONT", "QQQ", user_b))
            self.assertFalse(has_user_live_enabled("V2_SPY_TREND_CONT", user_b))
            self.assertFalse(is_user_authorized_ticker(
                "V2_SPY_TREND_CONT", "QQQ",
                {"paper_trading": True, "strategy_ticker_consents": user_a["strategy_ticker_consents"]},
            ))
            self.assertFalse(is_live_enabled_pair(
                "V2_SPY_TREND_CONT", "QQQ",
                {"paper_trading": True, "strategy_ticker_consents": user_a["strategy_ticker_consents"]},
            ))
            self.assertFalse(is_live_enabled_pair("V2_SPY_TREND_CONT", "SPY", user_a))

    def test_admin_publication_does_not_mutate_any_user_settings(self) -> None:
        user_settings = {"paper_trading": True}
        self._publish(qualified=False)
        self.assertEqual({"paper_trading": True}, user_settings)
        self.assertFalse(public_recommendations(user_settings)[0]["paper_enabled"])
        self.assertEqual("pending", public_recommendations(user_settings)[0]["decision"])

    def test_unpublished_pair_cannot_be_approved(self) -> None:
        with self.assertRaises(ValueError):
            save_user_consent({}, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled")

    def test_unqualified_publication_cannot_be_approved_for_paper(self) -> None:
        self._publish(qualified=False)
        with self.assertRaises(ValueError):
            save_user_consent(
                {"paper_trading": True}, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled",
            )

    def test_qualified_research_rule_can_enter_only_the_approved_paper_pair(self) -> None:
        from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids

        strategy_id = "CTX_VWAP_PULLBACK_KER10_LONG"
        publish_recommendation(
            strategy_id, "AAPL", evidence_summary="Forward AAPL option marks qualified.",
            qualification_verified=True,
        )
        settings = {
            "paper_trading": True,
            REVIEWED_STRATEGIES[strategy_id].setting_key: True,
        }
        settings["strategy_ticker_consents"] = save_user_consent(
            settings, strategy_id, "AAPL", "paper_enabled",
        )
        self.assertEqual(
            {strategy_id}, enabled_reviewed_strategy_ids(settings, ticker="AAPL", paper=True),
        )
        self.assertEqual(set(), enabled_reviewed_strategy_ids(settings, ticker="QQQ", paper=True))
        self.assertEqual(set(), enabled_reviewed_strategy_ids(settings, ticker="AAPL", paper=False))

    def test_approved_pair_is_added_to_only_that_users_dynamic_coverage(self) -> None:
        self._publish()
        user_a = {"paper_trading": True}
        user_a["strategy_ticker_consents"] = save_user_consent(user_a, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled")
        self.assertEqual(["QQQ"], approved_dynamic_tickers(user_a, {"V2_SPY_TREND_CONT"}))
        self.assertEqual([], approved_dynamic_tickers({"paper_trading": True}, {"V2_SPY_TREND_CONT"}))

    def test_failed_static_scope_does_not_keep_live_authority(self) -> None:
        publish_recommendation(
            "V2_SPY_TREND_CONT", "SPY",
            evidence_summary="Original reviewed pair still requires live qualification.",
        )
        settings = {"paper_trading": False}
        self.assertEqual("pending", public_recommendations(settings)[0]["decision"])
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "SPY", settings))

    def test_qualified_static_pair_can_be_user_approved_for_normal_live_execution(self) -> None:
        publish_recommendation(
            "V2_SPY_TREND_CONT", "SPY",
            evidence_summary="Exact SPY pair qualified.", qualification_verified=True,
        )
        with patch("config.strategy_live_promotion.review_live_promotion") as review:
            review.return_value.ready = True
            settings = {"paper_trading": False}
            settings["strategy_ticker_consents"] = save_user_consent(
                settings, "V2_SPY_TREND_CONT", "SPY", "live_enabled",
            )
            self.assertTrue(is_user_authorized_ticker("V2_SPY_TREND_CONT", "SPY", settings))
            self.assertTrue(is_live_enabled_pair("V2_SPY_TREND_CONT", "SPY", settings))

    def test_automation_rejects_nonqualified_evidence(self) -> None:
        with self.assertRaises(ValueError):
            publish_qualified_recommendation({
                "decision": "insufficient_evidence",
                "strategy_id": "V2_SPY_TREND_CONT",
                "strategy_version": "2.0.0",
                "ticker": "QQQ",
            }, evidence_artifact="data/latest.json")

    def test_automation_rejects_stale_strategy_version(self) -> None:
        with self.assertRaises(ValueError):
            publish_qualified_recommendation({
                "decision": "qualified",
                "strategy_id": "V2_SPY_TREND_CONT",
                "strategy_version": "1.0.0",
                "ticker": "QQQ",
            }, evidence_artifact="data/latest.json")

    def test_qualified_publication_still_requires_user_consent(self) -> None:
        publish_qualified_recommendation({
            "decision": "qualified",
            "strategy_id": "V2_SPY_TREND_CONT",
            "strategy_version": "2.0.0",
            "ticker": "QQQ",
            "holdout_start": "2026-08-01",
            "training": {"profit_factor": 1.4, "trading_days": 10},
            "holdout": {"profit_factor": 1.2, "trading_days": 4},
        }, evidence_artifact="data/latest.json")
        settings = {"paper_trading": True}
        self.assertEqual("pending", public_recommendations(settings)[0]["decision"])
        self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", settings))
