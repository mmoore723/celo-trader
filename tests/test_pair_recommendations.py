from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from strategy_health.pair_recommendations import assess, recommendations, decide
from strategy_health.research_matrix import completed_strategy_results
from strategy_health.exit_protocols import PROTOCOLS


def trades(profits, overlap=False):
    start = datetime(2026, 9, 10, 14, tzinfo=timezone.utc)
    return [{"id": str(i), "entry_at": (start + timedelta(minutes=i * (1 if overlap else 10))).isoformat(),
             "exit_at": (start + timedelta(minutes=i * (1 if overlap else 10) + (60 if overlap else 5))).isoformat(),
             "pnl": p} for i, p in enumerate(profits)]


class PairRecommendationTests(unittest.TestCase):
    def test_twenty_same_day_tests_can_pass_without_day_gate(self):
        result = assess(trades([20, 20, -10, 20, -10] * 4))
        self.assertTrue(result["qualified"])
        self.assertEqual(20, result["independent_trades"])

    def test_nineteen_is_not_qualified(self):
        self.assertFalse(assess(trades([20] * 19))["qualified"])

    def test_overlap_does_not_suppress_collection_or_inflate_decision(self):
        result = assess(trades([20] * 40, overlap=True))
        self.assertEqual(40, result["completed_trades"])
        self.assertEqual(1, result["independent_trades"])
        self.assertFalse(result["qualified"])

    def test_losing_validation_blocks_winning_history(self):
        result = assess(trades([20] * 14 + [-10] * 6))
        self.assertFalse(result["qualified"])
        self.assertIn("Latest 6 tests need PF 1.5 or higher", result["reasons"])

    def test_one_outlier_does_not_qualify(self):
        self.assertFalse(assess(trades([1000] + [1] * 19))["qualified"])

    def test_review_requires_ten_recent_losses_not_lifetime_pf(self):
        self.assertFalse(assess(trades([-10] * 9))["review_active"])
        self.assertTrue(assess(trades([100] * 30 + [-10] * 10))["review_active"])

    def test_invalid_results_cannot_qualify(self):
        self.assertEqual(0, assess([{"entry_at": "bad", "exit_at": "bad", "pnl": 50}])["completed_trades"])

    def test_all_runtime_strategies_can_reach_evidence_review_without_order_grant(self):
        from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES
        evidence = assess(trades([20, 20, -10, 20, -10] * 4))
        matrix = {"strategies": [{"strategy_id": sid, "version": spec.version,
                    "display_name": spec.display_name,
                    "pairs": [{"ticker": "META", "tradable": False, "recommendation": evidence}]}
                    for sid, spec in TESTED_RESEARCH_STRATEGIES.items()]}
        result = recommendations(matrix, {"paper_trading": True})
        self.assertEqual(16, len(result["recommendations"]))
        self.assertTrue(all(not r["can_enable"] and r["blocker"] for r in result["recommendations"]))
        first = result["recommendations"][0]
        with self.assertRaises(ValueError):
            decide(matrix, {}, first["strategy_id"], "META", "enable", evidence["fingerprint"])

    def test_review_choice_is_exact_pair_and_mode_and_does_not_touch_research(self):
        from config.strategy_catalog import REVIEWED_STRATEGIES
        sid = "V2_SPY_TREND_CONT"
        evidence = assess(trades([-10] * 10))
        matrix = {"strategies": [{"strategy_id": sid, "version": REVIEWED_STRATEGIES[sid].version,
                  "display_name": "Trend", "pairs": [{"ticker": "SPY", "tradable": True, "recommendation": evidence}]}]}
        settings = {"paper_trading": True, "strategy_spy_trend_cont_v2_enabled": True}
        updates = decide(matrix, settings, sid, "SPY", "research_only", evidence["fingerprint"])
        self.assertEqual({f"paper::{sid}:SPY": True}, updates["strategy_pair_pauses"])
        self.assertNotIn("research_strategy_ids", updates)
        self.assertNotIn("strategy_spy_trend_cont_v2_enabled", updates)
        from config.strategy_ticker_recommendations import is_user_authorized_ticker
        with patch("config.strategy_catalog.reviewed_strategy_integrity_errors", return_value={}):
            self.assertFalse(is_user_authorized_ticker(sid, "SPY", {**settings, **updates}))
            self.assertEqual(is_user_authorized_ticker(sid, "SPY", {**settings, "paper_trading": False}),
                             is_user_authorized_ticker(sid, "SPY", {**settings, **updates, "paper_trading": False}))
        kept = decide(matrix, settings, sid, "SPY", "keep_trading", evidence["fingerprint"])
        self.assertNotIn("strategy_pair_pauses", kept)
        self.assertEqual([], recommendations(matrix, {**settings, **kept})["recommendations"])
        with self.assertRaises(ValueError):
            decide(matrix, settings, sid, "SPY", "research_only", "stale")

    def test_authored_exit_requires_matching_contract_and_timely_quote(self):
        sid = "V2_VWAP_PULLBACK"
        sample = {"candidate_id": "a", "entry_ask": 2, "entry_contract": "META_TEST"}
        exit_row = {"protocol": PROTOCOLS[sid], "status": "priced", "entry_ask": 2, "bid": 3,
                    "contract_symbol": "META_TEST", "entry_quote_at": "2026-09-10T14:00:00Z",
                    "decision_at": "2026-09-10T14:30:00Z", "bid_at": "2026-09-10T14:30:01Z"}
        self.assertEqual(1, len(completed_strategy_results([sample], sid, {"a": exit_row}, 90)))
        self.assertEqual([], completed_strategy_results([sample], sid, {"a": {**exit_row, "contract_symbol": "OTHER"}}, 90))
        self.assertEqual([], completed_strategy_results([sample], sid, {"a": {**exit_row, "bid_at": "2026-09-10T14:36:00Z"}}, 90))

    def test_explicit_reapproval_is_only_for_matching_native_execution_and_account(self):
        from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids
        from config.strategy_ticker_recommendations import approved_dynamic_tickers
        sid = "V2_SPY_TREND_CONT"
        rule = REVIEWED_STRATEGIES[sid]
        evidence = assess(trades([20, 20, -10, 20, -10] * 4))
        matrix = {"strategies": [{"strategy_id": sid, "version": rule.version, "display_name": rule.display_name,
                  "pairs": [{"ticker": "SPY", "tradable": False, "recommendation": evidence}]}]}
        settings = {"paper_trading": True, "active_broker_account_id": "one", rule.setting_key: True}
        with patch("config.strategy_catalog.reviewed_strategy_integrity_errors", return_value={}):
            updates = decide(matrix, settings, sid, "SPY", "enable", evidence["fingerprint"])
            self.assertNotIn(rule.setting_key, updates)
            approved = {**settings, **updates}
            self.assertIn(sid, enabled_reviewed_strategy_ids(approved, ticker="SPY"))
            self.assertIn("SPY", approved_dynamic_tickers(approved, [sid]))
            self.assertNotIn(sid, enabled_reviewed_strategy_ids({**approved, rule.setting_key: False}, ticker="SPY"))
            self.assertNotIn(sid, enabled_reviewed_strategy_ids(approved, ticker="AAPL"))
            matrix['strategies'][0]['pairs'][0]['ticker'] = 'META'
            with self.assertRaisesRegex(ValueError, 'order-entry and exit route'):
                decide(matrix, settings, sid, 'META', 'enable', evidence['fingerprint'])


if __name__ == "__main__":
    unittest.main()
