"""The AI gate must produce replayable, candidate-linked calibration data."""
import unittest
from unittest.mock import patch

from ai_reasoning.client import CallResult
from ai_reasoning.decision_support import review_entry


class AiGateCandidateLinkTests(unittest.TestCase):
    def test_clean_approval_logs_candidate_and_structured_action(self) -> None:
        logged: list[dict] = []
        with patch(
            "ai_reasoning.decision_support.call_claude",
            return_value=CallResult(
                text="ACTION: approve | SIZE: 1.0 | EVIDENCE: none | REASON: deterministic checks remain authoritative.",
                latency_ms=12, model="test", error=None,
            ),
        ), patch("database.log_ai_reasoning", side_effect=lambda **kwargs: logged.append(kwargs)):
            result = review_entry(
                ticker="TSLA", strategy_id="V2_ORB_PULLBACK", direction="bullish",
                confidence=.81, rvol=1.4, contract_symbol="TSLA260821C00350000",
                option_type="call", strike=350.0, expiry="2026-08-21",
                n_contracts=1, entry_price=2.0, rr_ratio=1.8, paper=True,
                candidate_id="candidate-123",
            )

        self.assertEqual("approve", result.action)
        snapshot = logged[0]["feature_snapshot"]
        self.assertEqual("candidate-123", snapshot["candidate_id"])
        self.assertEqual("approve", snapshot["decision_action"])
        self.assertEqual(1.0, snapshot["decision_size_multiplier"])
        self.assertIsNone(snapshot["decision_error"])
        self.assertFalse(snapshot["decision_enforced"])
        self.assertFalse(logged[0]["applied"])

    def test_enforced_veto_is_the_only_kind_logged_as_applied(self) -> None:
        logged: list[dict] = []
        with patch(
            "ai_reasoning.decision_support.call_claude",
            return_value=CallResult(
                text="ACTION: veto | SIZE: 0 | EVIDENCE: trend_1h_bias,direction | REASON: trend_1h_bias is bearish while direction is bullish.",
                latency_ms=8, model="test", error=None,
            ),
        ), patch("database.log_ai_reasoning", side_effect=lambda **kwargs: logged.append(kwargs)):
            result = review_entry(
                ticker="TSLA", strategy_id="TESTED", direction="bullish",
                confidence=.81, rvol=1.4, contract_symbol="TSLA260821C00350000",
                option_type="call", strike=350.0, expiry="2026-08-21",
                n_contracts=1, entry_price=2.0, rr_ratio=1.8, paper=True,
                candidate_id="candidate-456", enforced=True, trend_1h_bias="bearish",
            )

        self.assertEqual("veto", result.action)
        self.assertTrue(logged[0]["feature_snapshot"]["decision_enforced"])
        self.assertTrue(logged[0]["applied"])

    def test_unsupported_veto_fails_open_when_evidence_was_not_supplied(self) -> None:
        logged: list[dict] = []
        with patch(
            "ai_reasoning.decision_support.call_claude",
            return_value=CallResult(
                text="ACTION: veto | SIZE: 0 | EVIDENCE: breaking_news | REASON: bad news is expected.",
                latency_ms=8, model="test", error=None,
            ),
        ), patch("database.log_ai_reasoning", side_effect=lambda **kwargs: logged.append(kwargs)):
            result = review_entry(
                ticker="SPY", strategy_id="V2_SPY_TREND_CONT", direction="bullish",
                confidence=.81, rvol=1.4, contract_symbol="SPY260821C00600000",
                option_type="call", strike=600.0, expiry="2026-08-21",
                n_contracts=1, entry_price=2.0, rr_ratio=1.8, paper=True,
                candidate_id="candidate-unsupported", enforced=True,
            )

        self.assertEqual("approve", result.action)
        self.assertIn("EVIDENCE fields absent", result.error or "")
        self.assertFalse(logged[0]["applied"])


if __name__ == "__main__":
    unittest.main()
