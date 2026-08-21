from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from config.strategy_ticker_recommendations import (
    approved_dynamic_tickers, consent_for, is_user_authorized_ticker, pair_key, public_recommendations,
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

    def _publish(self) -> None:
        publish_recommendation("V2_SPY_TREND_CONT", "QQQ", evidence_summary="Chronological quote validation passed.")

    def test_current_static_defaults_do_not_require_new_consent(self) -> None:
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

    def test_live_promoted_strategy_requires_exact_users_live_consent(self) -> None:
        self._publish()
        from config.strategy_catalog import REVIEWED_STRATEGIES
        live_rule = replace(REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"], paper_only=False)
        with patch.dict(REVIEWED_STRATEGIES, {"V2_SPY_TREND_CONT": live_rule}):
            user_a = {"paper_trading": False}
            user_a["strategy_ticker_consents"] = save_user_consent(
                user_a, "V2_SPY_TREND_CONT", "QQQ", "live_enabled",
            )
            user_b = {"paper_trading": False}
            self.assertTrue(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_a))
            self.assertFalse(is_user_authorized_ticker("V2_SPY_TREND_CONT", "QQQ", user_b))
            self.assertFalse(is_user_authorized_ticker(
                "V2_SPY_TREND_CONT", "QQQ",
                {"paper_trading": True, "strategy_ticker_consents": user_a["strategy_ticker_consents"]},
            ))

    def test_admin_publication_does_not_mutate_any_user_settings(self) -> None:
        user_settings = {"paper_trading": True}
        self._publish()
        self.assertEqual({"paper_trading": True}, user_settings)
        self.assertFalse(public_recommendations(user_settings)[0]["paper_enabled"])
        self.assertEqual("pending", public_recommendations(user_settings)[0]["decision"])

    def test_unpublished_pair_cannot_be_approved(self) -> None:
        with self.assertRaises(ValueError):
            save_user_consent({}, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled")

    def test_approved_pair_is_added_to_only_that_users_dynamic_coverage(self) -> None:
        self._publish()
        user_a = {"paper_trading": True}
        user_a["strategy_ticker_consents"] = save_user_consent(user_a, "V2_SPY_TREND_CONT", "QQQ", "paper_enabled")
        self.assertEqual(["QQQ"], approved_dynamic_tickers(user_a, {"V2_SPY_TREND_CONT"}))
        self.assertEqual([], approved_dynamic_tickers({"paper_trading": True}, {"V2_SPY_TREND_CONT"}))

    def test_existing_static_scope_cannot_be_published_as_new(self) -> None:
        with self.assertRaises(ValueError):
            publish_recommendation("V2_SPY_TREND_CONT", "SPY", evidence_summary="Already part of the reviewed scope.")

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
