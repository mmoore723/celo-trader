"""Regression tests for the V2 paid-study-aligned paper contract selector."""
from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from trading.entry.contract import select_reviewed_v2_contract, select_v2_orb_paper_contract
from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile


class _FakeTradier:
    def __init__(self, chains: dict[str, list[dict]]) -> None:
        self._chains = chains
        self._expirations = list(chains)

    def get_expirations(self, _ticker: str, **_window) -> list[str]:
        return self._expirations

    def get_option_chain(self, _ticker: str, expiry: str, _option_type: str) -> list[dict]:
        return self._chains[expiry]


class V2OrbPaperContractTests(unittest.TestCase):
    def setUp(self) -> None:
        # The UTC server is already on September 4; options DTE still uses
        # September 3 in New York. Pin both fixture expiries and the selector
        # to the same market clock instead of the machine's local date.
        now = datetime.fromisoformat("2026-09-03T20:05:00-04:00")
        self.market_date = now.date()
        clock = patch("trading.entry.contract._now_et", return_value=now)
        clock.start()
        self.addCleanup(clock.stop)

    def test_only_active_v2_pilots_use_the_paid_contract_profile(self) -> None:
        self.assertTrue(uses_v2_orb_execution_profile("V2_ORB_PULLBACK"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_SPY_TREND_CONT"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_SPY_AFTERNOON_FVG"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_TSLA_TWO_LEG_TREND_PULLBACK"))
        self.assertFalse(uses_v2_orb_execution_profile("MID_BRK"))
        self.assertTrue(uses_v2_orb_execution_profile("V2_TREND_CONT"))
        self.assertFalse(uses_v2_orb_execution_profile(None))

    def test_selects_nearest_expiry_then_nearest_otm_contract(self) -> None:
        near = (self.market_date + timedelta(days=7)).isoformat()
        later = (self.market_date + timedelta(days=14)).isoformat()
        broker = _FakeTradier({
            later: [{"symbol": "TSLA_LATER", "strike": 250, "bid": 2.80, "ask": 3.00}],
            near: [
                {"symbol": "TSLA_TOO_CHEAP", "strike": 249, "bid": 0.60, "ask": 0.70},
                {"symbol": "TSLA_NEAR", "strike": 251, "bid": 2.90, "ask": 3.00},
                {"symbol": "TSLA_FAR", "strike": 260, "bid": 3.80, "ask": 4.00},
            ],
        })
        contract, info = select_v2_orb_paper_contract(broker, "TSLA", "bullish", 250, 500)
        self.assertEqual("selected", info["reason"])
        self.assertEqual("TSLA_NEAR", contract["symbol"])
        self.assertEqual(7, info["selected_dte"])
        self.assertEqual("v2_orb_paid_tsla_near_money_otm_v1", contract["selection_model"])
        self.assertEqual(2, info["eligible_contract_count"])
        leaderboard = info["shadow_contract_leaderboard"]
        self.assertEqual("TSLA_NEAR", leaderboard[0]["symbol"])
        self.assertIn("reviewed_nearest_expiry_otm", leaderboard[0]["policy_winner_for"])
        policies = {policy for row in leaderboard for policy in row["policy_winner_for"]}
        self.assertEqual({
            "reviewed_nearest_expiry_otm", "tightest_spread", "lowest_ask",
            "highest_open_interest", "highest_volume", "closest_otm_strike",
            "closest_to_14_dte",
        }, policies)

    def test_rejects_non_tsla_and_wide_spread(self) -> None:
        expiry = (self.market_date + timedelta(days=7)).isoformat()
        broker = _FakeTradier({expiry: [{"symbol": "TSLA_WIDE", "strike": 251, "bid": 2.00, "ask": 3.00}]})
        contract, info = select_v2_orb_paper_contract(broker, "QQQ", "bullish", 250, 500)
        self.assertIsNone(contract)
        self.assertEqual("unsupported_v2_ticker", info["reason"])
        contract, info = select_v2_orb_paper_contract(broker, "TSLA", "bullish", 250, 500)
        self.assertIsNone(contract)
        self.assertEqual("illiquid", info["reason"])

    def test_spy_uses_the_same_reviewed_quote_rules_with_its_own_audit_label(self) -> None:
        expiry = (self.market_date + timedelta(days=7)).isoformat()
        broker = _FakeTradier({expiry: [{"symbol": "SPY_NEAR", "strike": 501, "bid": 2.90, "ask": 3.00}]})
        contract, info = select_v2_orb_paper_contract(broker, "SPY", "bullish", 500, 500)
        self.assertEqual("selected", info["reason"])
        self.assertEqual("v2_spy_trend_paid_near_money_otm_v1", contract["selection_model"])

    def test_out_of_scope_ticker_is_readable_for_research_but_not_orders(self) -> None:
        expiry = (self.market_date + timedelta(days=7)).isoformat()
        broker = _FakeTradier({expiry: [{"symbol": "AAPL_NEAR", "strike": 201, "bid": 2.90, "ask": 3.00}]})
        blocked, info = select_reviewed_v2_contract(
            broker, "AAPL", "bullish", 200, 500,
        )
        self.assertIsNone(blocked)
        self.assertEqual("unsupported_v2_ticker", info["reason"])
        observed, _ = select_reviewed_v2_contract(
            broker, "AAPL", "bullish", 200, 500, for_display=True,
        )
        self.assertEqual("AAPL_NEAR", observed["symbol"])
        promoted, _ = select_reviewed_v2_contract(
            broker, "AAPL", "bullish", 200, 500, approved_dynamic_match=True,
        )
        self.assertEqual("AAPL_NEAR", promoted["symbol"])


if __name__ == "__main__":
    unittest.main()
